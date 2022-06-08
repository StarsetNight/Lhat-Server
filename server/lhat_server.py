import re
import socket
import selectors  # IO多路复用
import os
import sys
import json
import types
import threading
import sqlite3

from server_operations import *
import settings  # 导入配置文件


ip = settings.ip_address
port = settings.network_port
default_room = settings.default_chatting_room
password = settings.password
root_password = settings.root_password
logable = settings.log
recordable = settings.record
force_account = settings.force_account

# SQL命令，用于便捷地操作数据库
create_table = settings.create_table
append_user = settings.append_user
delete_user = settings.delete_user
get_user_info = settings.get_user_info
reset_user_password = settings.reset_user_password
set_permission = settings.set_permission


class FileClient:
    """
    文件客户端类，专门用于文件传输。
    """
    def __init__(self, conn, address, file_id, file_name, file_size):
        """
        初始化文件客户端类。
        :param conn: 客户端连接
        :param address: 客户端地址
        :param file_id: 文件id
        :param file_name: 文件名
        :param file_size: 文件大小
        """
        self.connection = conn
        self.address = address
        self.file_id = file_id
        self.file_name = file_name
        self.file_size = file_size
        self.file_path = os.path.join(os.getcwd(), 'files', file_name)

    def startReceive(self, file_list):
        """
        开始接收文件。
        """
        if os.path.exists(self.file_path):
            self.connection.send(bytes('FILE_EXIST', 'utf-8'))
            self.connection.close()
        else:
            self.connection.send(bytes('RECEIVING', 'utf-8'))
            with open(self.file_path, 'wb') as f:
                while True:
                    data = self.connection.recv(1024)
                    if data == b'':
                        break
                    f.write(data)
            self.connection.close()
            file_list[self.file_id] = self.file_path

    def startSend(self, recv_id, file_list):
        if recv_id in file_list:
            self.connection.send(bytes('SENDING', 'utf-8'))
            with open(file_list[recv_id], 'rb') as f:
                while True:
                    data = f.read(1024)
                    if data == b'':
                        break
                    self.connection.send(data)
            self.connection.close()


class User:
    """
    用户类，用于存储每个连接到本服务器的客户端的信息。
    """

    def __init__(self, conn, address, permission, passwd, id_num, name):
        """
        初始化客户端
        """
        self._socket = conn  # 客户端的socket
        self._address = address  # 客户端的ip地址
        self._username = name  # 客户端的用户名
        self._rooms = [default_room]  # 客户端所在的房间
        self.__id_num = id_num  # 客户端的id号
        if password == passwd:
            self.__permission = permission
        else:
            print('Incorrect password!')
            self.__permission = 'User'

    def getPermission(self) -> str:
        """
        获取客户端的权限
        """
        return self.__permission

    def setPermission(self, permission='User', passwd=None):
        """
        设置客户端的权限
        """
        if permission == 'User':
            self.__permission = 'User'
        elif root_password == passwd:
            self.__permission = permission
        else:
            print('Incorrect password!')

    def getId(self) -> int:
        """
        获取客户端的id号
        """
        return self.__id_num

    def getSocket(self) -> socket.socket:
        """
        获取客户端的socket
        """
        return self._socket

    def getUserName(self) -> str:
        """
        获取客户端的用户名
        """
        return self._username

    def getRooms(self) -> list:
        """
        获取客户端所在的房间
        """
        return self._rooms

    def addRoom(self, room: str):
        """
        客户端加入房间
        :param room: 房间名，字符串
        """
        if room not in self._rooms:
            self._rooms.append(room)
        else:
            print('The room already exists!')

    def removeRoom(self, room: str):
        """
        客户端退出房间
        """
        if room == default_room:
            print('Leaving the default room is not allowed!')
        elif room in self._rooms:
            self._rooms.remove(room)
        else:
            print('The room does not exist!')

    def getAddress(self) -> tuple:
        """
        获取客户端的ip地址
        """
        return self._address


class Server:
    """
    服务器类，用于接收客户端的请求，并调用相应的操作
    """
    def __init__(self):
        """
        初始化服务器
        """
        if not os.path.exists('records'):
            os.mkdir('records')
        if not os.path.exists('logs'):
            os.mkdir('logs')
        if not os.path.exists('sql'):
            os.mkdir('sql')
        self.log('=====NEW SERVER INITIALIZING BELOW=====', show_time=False)
        self.user_connections = {}  # 创建一个空的用户连接列表
        self.need_handle_messages = []  # 创建一个空的消息队列
        self.chatting_rooms = [default_room]  # 创建一个聊天室列表
        self.sql_exist_user = []  # 数据库中的用户
        self.client_id = 0  # 创建一个id，用于给每个连接分配一个id
        self.log('Initializing server... ', end='')
        self.select = selectors.DefaultSelector()  # 创建IO多路复用
        self.main_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # 创建socket
        self.main_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
        self.log('Done!', show_time=False)
        self.log('Now the server can be ran.')

        self.sql_connection = sqlite3.connect('sql/server.db', check_same_thread=False)
        self.log('SQLite3 database connected.')
        self.sql_cursor = self.sql_connection.cursor()
        self.log('SQLite3 cursor created.')
        self.sql_cursor.execute(create_table)
        self.sql_connection.commit()
        self.log('USERS table exists now.')
        self.sql_cursor.execute('SELECT USER_NAME FROM USERS')
        for name in self.sql_cursor:
            self.sql_exist_user.append(name[0])
        if 'root' not in self.sql_exist_user:
            self.sql_cursor.execute(append_user, ('root', '25d55ad283aa400af464c76d713c07ad', 'Admin'))
            self.sql_exist_user.append('root')
            self.log('Root account not found, created.')
        else:
            self.sql_cursor.execute(set_permission, ('Admin', 'root'))
        self.sql_connection.commit()


    def run(self):
        """
        启动服务器
        :return: 无返回值，因为服务器一直运行，直到程序结束
        """
        # main_sock是用于监听的socket，用于接收客户端的连接
        self.main_sock.bind((ip, port))
        self.main_sock.listen(20)  # 监听，最多accept 20个连接数
        self.log('================================')
        self.log(f'Running server on {ip}:{port}')
        self.log('  To change the settings, \n  please visit settings.py')
        if force_account:
            self.log('Warning, force account is enabled!!! \n'
                     '  Guest won\'t be able to login.')
        self.log('Waiting for connection...')
        self.main_sock.setblocking(False)  # 设置为非阻塞
        self.select.register(self.main_sock, selectors.EVENT_READ, data=None)  # 注册socket到IO多路复用，以便于多连接
        while True:
            events = self.select.select(timeout=None)  # 阻塞等待IO事件
            for key, mask in events:  # 事件循环，key用于获取连接，mask用于获取事件类型
                if key.data is None:  # 如果是新连接
                    self.createConnection(key.fileobj)  # 接收连接
                else:  # 如果是已连接
                    self.serveClient(key, mask)  # 处理连接
            time.sleep(0.0001)  # 因为是阻塞的，所以sleep不会漏消息，同时降低负载

    def createConnection(self, sock: socket.socket):
        """
        创建一个新连接
        :param sock: 创建的socket对象
        :return: 无返回值
        """
        conn, address = sock.accept()  # 接收连接，并创建一个新的连接
        self.log(f'Connection established: {address[0]}:{address[1]}')
        conn.setblocking(False)  # 设置为非阻塞
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)  # 设置为非延迟发送
        namespace = types.SimpleNamespace(address=address, inbytes=b'')  # 创建一个空的命名空间，用于存储连接信息
        self.select.register(conn, selectors.EVENT_READ | selectors.EVENT_WRITE,
                             data=namespace)  # 注册连接到IO多路复用，以便于多连接

    def serveClient(self, key, mask):
        """
        用于服务客户端的函数
        :param key: 传入的键，内含很多成员变量
        :param mask: 用于判断客户端目前是否可用，是一个布尔变量
        :return: 无返回值
        """
        sock = key.fileobj  # 获取socket
        data = key.data  # 获取命名空间
        if mask & selectors.EVENT_READ:  # 如果可读，则开始从客户端读取消息
            try:
                data.inbytes = sock.recv(1024)  # 从客户端读取消息
            except ConnectionError:  # 如果读取失败，则说明客户端已断开连接
                self.closeConnection(sock, data.address)
                return
            if data.inbytes:  # 如果消息列表不为空
                try:
                    data.inbytes.decode('utf-8')
                except UnicodeDecodeError:
                    self.log('A message is not in utf-8 encoding.')
                else:
                    self.need_handle_messages.append(data.inbytes)
                data.inbytes = b''
            else:
                self.closeConnection(sock, data.address)  # 如果读取失败，则关闭连接
                return

        if mask & selectors.EVENT_WRITE:  # 如果可写，向客户端发送消息
            if self.need_handle_messages:
                for processing_message in self.need_handle_messages:
                    try:
                        # 如果该项为空，就转到下一个遍历，反之处理它
                        if processing_message:
                            self.processMessage(processing_message, sock, data.address)
                        else:
                            continue
                    except ConnectionResetError:  # 服务端断开连接
                        self.closeConnection(sock, data.address)
                        return
                self.need_handle_messages = []
                time.sleep(0.0005)  # 粘包现象很恶心，sleep暂时能解决

    def processMessage(self, message: str, sock: socket.socket, address=None):
        """
        处理消息，让服务器决定如何处理
        :param message: 待处理的消息
        :param sock: 客户端连接
        :param address: 客户端地址
        :return: 无返回值
        """
        if not message:  # 客户端发送了空消息，于是直接断连
            self.closeConnection(sock, address)
            return
        recv_data = unpack(message)  # 解码消息
        time.sleep(0.0005)  # 延迟，防止粘包
        if recv_data[0] == 'TEXT_MESSAGE' or recv_data[0] == 'COLOR_MESSAGE':  # 如果能正常解析，则进行处理
            if recv_data[1] == default_room:  # 默认聊天室的群聊
                self.record(message)
                for sending_sock in self.user_connections.values():  # 直接发送
                    sending_sock.getSocket().send(message)
            # 这里可能有点疑惑，默认聊天室明明也在chatting_rooms里，这里不会出问题吗？
            # 回答是，不会的。因为只要第一个if条件过不去，那么这就不是默认聊天室了，而是其他聊天室或私聊
            elif recv_data[1] in self.chatting_rooms:  # 如果是其他聊天室的群聊
                print(f'Other room\'s message received: {recv_data[3]}')
                for sending_sock in self.user_connections.values():
                    if recv_data[1] in sending_sock.getRooms():  # 如果该用户在该聊天室
                        sending_sock.getSocket().send(message)
            else:
                print(f'Private message received [{recv_data[3]}]')
                for sending_sock in self.user_connections.values():  # 私聊
                    if sending_sock.getUserName() == recv_data[1] or \
                            sending_sock.getUserName() == recv_data[2]:  # 遍历所有用户，找到对应用户
                        # 第一个表达式很好理解，发给谁就给谁显示，第二个表达式则是自己发送，但是也得显示给自己
                        sending_sock.getSocket().send(message)  # 发送给该用户

        elif recv_data[0] == 'COMMAND':
            command = recv_data[2].split(' ')  # 分割命令
            command.append('')
            time.sleep(0.001)
            if command[0] == 'room':
                room_name = ' '.join(command[2:])  # 将命令分割后的后面的部分合并为一个字符串
                if command[1] == 'create':
                    self.log(f'{recv_data[1]} wants to create room {room_name}')
                    if self.user_connections[recv_data[1]].getPermission() != 'User':  # 如果不是普通用户
                        if room_name in self.chatting_rooms or room_name in self.user_connections:
                            self.log(f'Room {room_name} already exists, abort creating.')
                            sock.send(pack(f'{room_name} 已存在，无法创建。', 'Server', None, 'TEXT_MESSAGE'))
                        else:
                            self.chatting_rooms.append(room_name)
                            self.log(f'Room {room_name} created.')
                            for name, user in self.user_connections.items():
                                if name == recv_data[1]:
                                    user.addRoom(room_name)
                                    sock.send(pack(f'成功创建并加入聊天室 {room_name}。', 'Server', None, 'TEXT_MESSAGE'))
                    else:
                        self.log(f'User {recv_data[1]} is not allowed to create room.')
                        sock.send(pack(f'你没有创建聊天室的权限。', 'Server', None, 'TEXT_MESSAGE'))
                elif command[1] == 'join':
                    self.log(f'{recv_data[1]} join room {room_name}')
                    if room_name in self.chatting_rooms:
                        for name, user in self.user_connections.items():
                            if name == recv_data[1]:
                                user.addRoom(room_name)
                                sock.send(pack(f'你已成功加入聊天室 {room_name}。', 'Server', None, 'TEXT_MESSAGE'))
                    else:
                        self.log(f'Room {room_name} does not exist, abort joining.')
                        sock.send(pack(f'{room_name} 不存在，无法加入。', 'Server', None, 'TEXT_MESSAGE'))
                elif command[1] == 'list':
                    self.log(f'{recv_data[1]} wants to check online rooms.')
                    sock.send(pack(f'当前聊天室有：{self.chatting_rooms}<br/>'
                                   f'你已加入的聊天室有：{self.user_connections[recv_data[1]].getRooms()}',
                                   'Server', None, 'TEXT_MESSAGE'))
                elif command[1] == 'leave':
                    self.log(f'{recv_data[1]} wants to leave room {room_name}')
                    if room_name in self.chatting_rooms:
                        for name, user in self.user_connections.items():
                            if name == recv_data[1]:
                                user.removeRoom(room_name)
                                sock.send(pack(f'你已成功退出聊天室 {room_name}。', 'Server', None, 'TEXT_MESSAGE'))
                    else:
                        self.log(f'Room {room_name} does not exist, abort leaving.')
                        sock.send(pack(f'{room_name} 不存在，无法退出。', 'Server', None, 'TEXT_MESSAGE'))
                elif command[1] == 'delete':
                    self.log(f'{recv_data[1]} wants to delete room {room_name}')
                    if self.user_connections[recv_data[1]].getPermission() == 'Admin':
                        if room_name in self.chatting_rooms:
                            self.chatting_rooms.remove(room_name)
                            self.log(f'Room {room_name} deleted.')
                            for user in self.user_connections.values():
                                if room_name in user.getRooms():
                                    user.removeRoom(room_name)
                                    user.getSocket().send(pack(f'{room_name} 聊天室已被管理员删除，已自动退出本聊天室。',
                                                               'Server', None, 'TEXT_MESSAGE'))
                                sock.send(pack(f'已删除聊天室 {room_name}。', 'Server', None, 'TEXT_MESSAGE'))
                        else:
                            self.log(f'Room {room_name} does not exist, abort deleting.')
                            sock.send(pack(f'{room_name} 不存在，无法删除。', 'Server', None, 'TEXT_MESSAGE'))
                    else:
                        self.log(f'{recv_data[1]} do not have the permission to delete {room_name}.')
                        sock.send(pack(f'你没有权限删除聊天室 {room_name}。',
                                       'Server', None, 'TEXT_MESSAGE'))
                time.sleep(0.0005)
                sock.send(pack(json.dumps(self.user_connections[recv_data[1]].getRooms()),
                               'Server', None, 'ROOM_MANIFEST'))

            elif command[0] == 'root':
                self.log(f'{recv_data[1]} wants to change his permission.')
                if command[1] == root_password:
                    self.user_connections[recv_data[1]].setPermission('Admin', command[1])
                    self.log(f'{recv_data[1]} permission changed to Admin.')
                    sock.send(pack(f'你已获得最高管理员权限。', 'Server', None, 'TEXT_MESSAGE'))
                elif not command[1]:
                    self.user_connections[recv_data[1]].setPermission('User')
                    self.log(f'{recv_data[1]} permission changed to User.')
                    sock.send(pack(f'你已放弃最高管理员权限。', 'Server', None, 'TEXT_MESSAGE'))
                else:
                    self.log(f'{recv_data[1]} password is incorrect.')
                    sock.send(pack(f'最高管理员登录密码错误。', 'Server', None, 'TEXT_MESSAGE'))

            elif command[0] == 'manager':
                operate_user = ' '.join(command[2:])
                if self.user_connections[recv_data[1]].getPermission() == 'Admin':
                    if command[1] == 'add':
                        self.log(f'{recv_data[1]} wants to add {operate_user} to the Manager group.')
                        if operate_user in self.user_connections and \
                                self.user_connections[operate_user].getPermission() == 'User':
                            self.user_connections[operate_user].setPermission('Manager', root_password)
                            self.log(f'{operate_user} permission changed to Manager.')
                            self.user_connections[operate_user].getSocket().send(
                                pack(f'你已被最高管理员添加为维护者。', 'Server', None, 'TEXT_MESSAGE')
                            )
                            sock.send(pack(f'{operate_user} 已获得维护者权限。', 'Server', None, 'TEXT_MESSAGE'))
                        else:
                            sock.send(pack(f'{operate_user} 不存在或拥有更高权限，无法获得维护者权限。', 'Server', None, 'TEXT_MESSAGE'))
                    elif command[1] == 'remove':
                        self.log(f'{recv_data[1]} wants to remove {operate_user} from the Manager group.')
                        if operate_user in self.user_connections and \
                                self.user_connections[operate_user].getPermission() == 'Manager':
                            self.user_connections[operate_user].setPermission('User')
                            self.log(f'{operate_user} permission changed to User.')
                            self.user_connections[operate_user].getSocket().send(
                                pack(f'你已被最高管理员撤掉维护者。', 'Server', None, 'TEXT_MESSAGE')
                            )
                            sock.send(pack(f'{operate_user} 已撤掉维护者权限。', 'Server', None, 'TEXT_MESSAGE'))
                        else:
                            sock.send(pack(f'{operate_user} 不存在或拥有其他权限，无法撤掉维护者权限。', 'Server', None, 'TEXT_MESSAGE'))
                    elif command[1] == 'list':
                        self.log(f'{recv_data[1]} wants to list all managers.')
                        sock.send(pack(json.dumps(self.getManagers()), 'Server', None, 'MANAGER_LIST'))
                else:
                    if command[1] == 'list':
                        self.log(f'{recv_data[1]} wants to list all managers.')
                        sock.send(pack(json.dumps(self.getManagers()), 'Server', None, 'MANAGER_LIST'))
                    else:
                        self.log(f'{recv_data[1]} do not have the permission to manage users.')
                        sock.send(pack(f'你没有最高权限以用于管理用户。', 'Server', None, 'TEXT_MESSAGE'))

            elif command[0] == 'kick':
                self.log(f'{recv_data[1]} wants to kick {" ".join(command[1:])}.')
                if self.user_connections[recv_data[1]].getPermission() != 'User':
                    if " ".join(command[1:]) in self.user_connections and \
                            self.user_connections[" ".join(command[1:])].getPermission() == 'User':
                        self.user_connections[" ".join(command[1:])].getSocket().send(pack(
                            f'你已被管理员踢出服务器。', 'Server', None, 'TEXT_MESSAGE'))
                        self.closeConnection(self.user_connections[" ".join(command[1:])].getSocket(),
                                             self.user_connections[" ".join(command[1:])].getAddress())
                        self.log(f'{" ".join(command[1:])} kicked.')
                        sock.send(pack(f'你已成功踢出 {" ".join(command[1:])}。', 'Server', None, 'TEXT_MESSAGE'))
                    else:
                        if recv_data[1] == " ".join(command[1:]):
                            self.log(f'{recv_data[1]} tried to kick himself.')
                            sock.send(pack(f'自己踢自己？搁这卡bug呢？', 'Server', None, 'TEXT_MESSAGE'))
                            for sending_sock in self.user_connections.values():  # 直接发送
                                sending_sock.getSocket().send(pack(f'[新闻] 人类迷惑行为：{recv_data[1]} 试图把自己踢出服务器。',
                                                                   'Server', None, 'TEXT_MESSAGE'))
                        else:
                            self.log(f'{" ".join(command[1:])} does not exist, abort kicking.')
                            sock.send(pack(f'{" ".join(command[1:])} 不存在或为管理员，无法踢出。<br/>'
                                           f'也许你该先把对方的管理员撤了？', 'Server', None, 'TEXT_MESSAGE'))
                else:
                    self.log(f'{recv_data[1]} do not have the permission to kick {" ".join(command[1:])}.')
                    sock.send(pack(f'你没有权限踢出 {" ".join(command[1:])}，先看看自己有没有这个权限再说吧。', 'Server', None, 'TEXT_MESSAGE'))

            elif command[0] == 'update':
                self.log(f'{recv_data[1]} wants to update his user manifest manually.')
                sock.send(pack(json.dumps(self.getOnlineUsers()), 'Server', default_room, 'USER_MANIFEST'))
                time.sleep(0.0005)
                sock.send(pack('你已成功更新用户列表。', 'Server', None, 'TEXT_MESSAGE'))

        elif recv_data[0] == 'DO_NOT_PROCESS':
            for sending_sock in self.user_connections.values():
                sending_sock.getSocket().send(message)

        elif recv_data[0] == 'USER_NAME':  # 如果是用户名
            threading.Thread(target=self.processNewLogin, args=(sock, address, recv_data[1])).start()

    def processNewLogin(self, sock, address, user_info):
        """处理新登录的客户端"""
        try:
            user, passwd = user_info.split('\r\n')
        except ValueError:
            user = user_info.strip()
            passwd = None
        if passwd:
            if user in self.user_connections:
                self.log(f'{user} tried to login again.')
                sock.send(pack(f'请不要重复登录。', 'Server', None, 'TEXT_MESSAGE'))
                self.closeConnection(sock, address)
                return
            try:
                self.sql_cursor.execute('SELECT * FROM USERS WHERE USER_NAME=? AND PASSWORD=?', (user, passwd))
            except sqlite3.OperationalError as err:
                print(err)
                self.log(f'{user} tried to login with a wrong password.')
                sock.send(pack(f'用户名或密码错误。', 'Server', None, 'TEXT_MESSAGE'))
                self.closeConnection(sock, address)
                return
            if not self.sql_cursor.fetchone():
                self.log(f'{user} tried to login with a wrong password.')
                sock.send(pack(f'用户名或密码错误。', 'Server', None, 'TEXT_MESSAGE'))
                self.closeConnection(sock, address)
                return
        elif force_account:
            self.log(f'{user} tried to login without password.')
            sock.send(pack('该服务器启用了强制用户系统，请使用帐号登录。', 'Server', None, 'TEXT_MESSAGE'))
            self.closeConnection(sock, address)
            return

        new_port = str(address[1])
        sock.send(pack(default_room, None, None, 'DEFAULT_ROOM'))  # 发送默认群聊
        if user == '用户名不存在' or not user:  # 如果客户端未设定用户名
            user = address[0] + ':' + new_port  # 直接使用IP和端口号
        elif user in self.chatting_rooms:  # 如果用户名已经存在
            user += new_port  # 用户名和端口号
        user = user[:20].strip()  # 如果用户名过长，则截断并去除首尾空格
        for client in self.user_connections.values():
            if client.getUserName() == user:  # 如果重名，则添加数字（端口不会重复）
                user += new_port
            # 将用户名加入连接列表

        # User类的实例化参数：conn, address, permission, passwd, id_num
        self.user_connections[user] = \
            User(sock, address, 'User', '123456', self.client_id, user)  # 将用户名和连接加入连接列表

        online_users = self.getOnlineUsers()  # 获取在线用户
        time.sleep(0.2)  # 等待一下，否则可能会出现粘包
        for sending_sock in self.user_connections.values():  # 开始发送用户列表
            sending_sock.getSocket().send(pack(json.dumps(online_users), None, default_room, 'USER_MANIFEST'))

    def getOnlineUsers(self) -> list:
        """
        获取在线用户
        :return: 在线用户列表
        """
        online_users = []
        for user in self.user_connections.values():
            online_users.append(user.getUserName())
        return online_users

    def getManagers(self) -> list:
        """
        获取在线管理员
        :return: 在线管理员列表
        """
        managers = []
        for user in self.user_connections.values():
            if user.getPermission() == 'Manager':
                managers.append(user.getUserName())
        return managers

    def closeConnection(self, sock: socket.socket, address: tuple):
        """
        关闭连接
        :param sock: 已知的无效连接
        :param address: 连接的地址
        :return: 无返回值
        """
        self.log(f'Connection closed: {address[0]}:{address[1]}')  # 日志
        self.select.unregister(sock)  # 从IO多路复用中移除连接
        for cid in list(self.user_connections):
            if self.user_connections[cid].getSocket() == sock:
                del self.user_connections[cid]  # 删除连接
        online_users = self.getOnlineUsers()
        for sending_sock in self.user_connections.values():
            sending_sock.getSocket().send(pack(json.dumps(online_users), None, default_room, 'USER_MANIFEST'))
        sock.close()

    @staticmethod
    def log(content: str, end='\n', show_time=True):
        """
        日志
        :param content: 日志内容
        :param end: 日志结尾
        :param show_time: 是否显示时间
        :return: 无返回值
        """
        if show_time:
            print(f'[{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}] {content}', end=end)
        else:
            print(content, end=end)
        if logable:
            with open(f'logs/lhat_server{time.strftime("%Y-%m-%d", time.localtime())}.log', 'a') as f:
                f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}] {content}{end}')

    @staticmethod
    def record(message):
        """
        记录聊天消息
        :param message: 记录内容
        :return: 无返回值
        """
        print(message)
        if recordable:
            with open('records/lhat_chatting_record.txt', 'a') as f:
                if isinstance(message, str):
                    f.write(message + '\n')
                elif isinstance(message, bytes):
                    f.write(message.decode('utf-8') + '\n')


if __name__ == '__main__':
    server = Server()  # 创建一个服务器对象
    server.run()  # 启动服务器

import socket
import selectors  # IO多路复用
import os
import types
import threading
import sqlite3
import hashlib

from server_operations import *
from defines import settings
from defines.User import User

# SQL命令，用于便捷地操作数据库
create_table = settings.create_table
append_user = settings.append_user
delete_user = settings.delete_user
get_user_info = settings.get_user_info
reset_user_password = settings.reset_user_password
set_permission = settings.set_permission


class Server:
    """
    服务器类，用于接收客户端的请求，并调用相应的操作
    """
    # INFORMATION
    VERSION: str = settings.VERSION  # Lhat Server版本
    ip: str = settings.ip_address  # 服务器IP地址
    port: int = settings.network_port  # 服务器端口
    default_room: str = settings.default_room  # 默认聊天室名称

    # SETTINGS
    logable: bool  # 是否记录日志
    recordable: bool  # 是否记录聊天记录
    force_account: bool  # 是否强制用户系统，为True时，游客无法加入聊天室
    allow_register: bool  # 是否允许注册新用户，Manager权限以上可以在运行后更改

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
        if not os.path.exists('files'):
            os.mkdir('files')
        print(f'Lhat Chatting Server Version {self.VERSION} using AGPL v3.0 License')
        self.logable = settings.log
        self.recordable = settings.record
        self.force_account = settings.force_account
        self.allow_register = settings.allow_register
        self.log('Server arguments set.')
        self.log('=====NEW SERVER INITIALIZING BELOW=====', show_time=False)
        self.user_connections = {}  # 创建一个空的用户连接列表
        self.need_handle_messages = []  # 创建一个空的消息队列
        self.chatting_rooms = [self.default_room]  # 创建一个聊天室列表
        self.sql_exist_user = []  # 数据库中的用户
        self.client_id = 0  # 创建一个id，用于给每个连接分配一个id
        self.log('Initializing server... ', end='')
        self.select = selectors.DefaultSelector()  # 创建IO多路复用
        self.main_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # 创建socket
        self.main_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
        self.log('Done!', show_time=False)
        self.log('Now the server can be ran.')

        self.sql_connection = sqlite3.connect('sql/server.db', check_same_thread=False)  # 创建数据库连接
        self.log('SQLite3 database connected.')
        self.sql_cursor = self.sql_connection.cursor()  # 创建数据库游标
        self.log('SQLite3 cursor created.')
        self.sql_cursor.execute(create_table)  # 创建数据库表，名为USERS
        self.sql_connection.commit()
        self.log('USERS table exists now.')
        self.sql_cursor.execute('SELECT USER_NAME FROM USERS')  # 获取数据库中的用户名
        for name in self.sql_cursor:
            self.sql_exist_user.append(name[0])  # 将用户名添加到列表中
        if 'root' not in self.sql_exist_user:  # 如果数据库中没有root用户，则创建
            self.sql_cursor.execute(append_user, ('root', '25d55ad283aa400af464c76d713c07ad', 'Admin', 0))
            self.sql_exist_user.append('root')
            self.log('Root account not found, created.')
        else:  # 如果数据库中有root用户，则检查权限是否正确
            self.sql_cursor.execute(set_permission, ('Admin', 'root'))
        self.sql_connection.commit()

    def run(self):
        """
        启动服务器
        :return: 无返回值，因为服务器一直运行，直到程序结束
        """
        # main_sock是用于监听的socket，用于接收客户端的连接
        self.main_sock.bind((self.ip, self.port))
        self.main_sock.listen(20)  # 监听，最多accept 20个连接数
        self.log('================================', show_time=False)
        self.log(f'Running server on {self.ip}:{self.port}')
        self.log('  To change the settings, \n  please visit settings.py')
        if self.force_account:
            self.log('Warning, force account is enabled!!! \n'
                     '  Guest will not be able to login.')
        self.log('Waiting for connection...')
        self.main_sock.setblocking(False)  # 设置为非阻塞
        self.select.register(self.main_sock, selectors.EVENT_READ, data='')  # 注册socket到IO多路复用，以便于多连接
        while True:
            events = self.select.select(timeout=None)  # 阻塞等待IO事件
            for key, mask in events:  # 事件循环，key用于获取连接，mask用于获取事件类型
                if key.data == '':  # 如果是新连接
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
                    data.inbytes = data.inbytes.strip(b'\x00\xcc\0')  # 尝试解码
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
            if recv_data[1] == self.default_room:  # 默认聊天室的群聊
                self.record(message)
                for sending_sock in self.user_connections.values():  # 直接发送
                    sending_sock.getSocket().send(message)
            # 这里可能有点疑惑，默认聊天室明明也在chatting_rooms里，这里不会出问题吗？
            # 回答是，不会的。因为只要第一个if条件过不去，那么这就不是默认聊天室了，而是其他聊天室或私聊
            elif recv_data[1] in self.chatting_rooms:  # 如果是其他聊天室的群聊
                print(f'Other rooms message received: {recv_data[3]}')
                for sending_sock in self.user_connections.values():
                    if recv_data[1] in sending_sock.getRooms():  # 如果该用户在该聊天室
                        sending_sock.getSocket().send(message)
            else:  # 私聊
                print(f'Private message received [{recv_data[3]}]')
                """
                for sending_sock in self.user_connections.values():
                    if sending_sock.getUserName() == recv_data[1] or \
                            sending_sock.getUserName() == recv_data[2]:  # 遍历所有用户，找到对应用户
                        # 第一个表达式很好理解，发给谁就给谁显示，第二个表达式则是自己发送，但是也得显示给自己
                        sending_sock.getSocket().send(message)  # 发送给该用户
                """
                # 显然遍历没下标好
                if recv_data[1] in self.user_connections:
                    sock.send(message)
                    self.user_connections[recv_data[1]].getSocket().send(message)
                else:
                    sock.send(pack("私聊目标用户不存在。", "Server", "", "TEXT_MESSAGE"))

        elif recv_data[0] == 'SEND_FILE':
            print(f'File sending request received: {recv_data[1]}')
            # 待办: 发送及接收文件

        elif recv_data[0] == 'COMMAND':
            # 客户端会发送命令，于是服务器应该根据命令进行相应的处理
            command = recv_data[2].split(' ')  # 分割命令
            time.sleep(0.001)
            try:
                if command[0] == 'room':
                    room_name = ' '.join(command[2:])  # 将命令分割后的后面的部分合并为一个字符串
                    if command[1] == 'create':  # 创建聊天室，需要Manager以上权限
                        self.log(f'{recv_data[1]} wants to create room {room_name}')
                        if self.user_connections[recv_data[1]].getPermission() != 'User':  # 如果不是普通用户
                            if room_name in self.chatting_rooms or room_name in self.user_connections:
                                self.log(f'Room {room_name} already exists, abort creating.')
                                sock.send(pack(f'Room {room_name} already exists, abort creating.', 'Server', '',
                                               'TEXT_MESSAGE'))
                            else:  # 如果聊天室不存在，则创建聊天室
                                self.chatting_rooms.append(room_name)
                                self.log(f'Room {room_name} created.')
                                for name, user in self.user_connections.items():
                                    if name == recv_data[1]:
                                        user.addRoom(room_name)
                                        sock.send(pack(f'Room {room_name} created.', 'Server', '', 'TEXT_MESSAGE'))
                        else:
                            self.log(f'User {recv_data[1]} is not allowed to create room.')
                            sock.send(pack(f'你没有创建聊天室的权限。', 'Server', '', 'TEXT_MESSAGE'))
                    elif command[1] == 'join':  # 加入聊天室
                        self.log(f'{recv_data[1]} join room {room_name}')
                        if room_name in self.chatting_rooms:
                            for name, user in self.user_connections.items():
                                if name == recv_data[1]:
                                    user.addRoom(room_name)
                                    sock.send(pack(f'你已成功加入聊天室 {room_name}。', 'Server', '', 'TEXT_MESSAGE'))
                        else:
                            self.log(f'Room {room_name} does not exist, abort joining.')
                            sock.send(pack(f'{room_name} 不存在，无法加入。', 'Server', '', 'TEXT_MESSAGE'))
                    elif command[1] == 'list':  # 列出所有聊天室
                        self.log(f'{recv_data[1]} wants to check online rooms.')
                        sock.send(pack(f'Now online rooms: {self.chatting_rooms}\n'
                                       f'You joined: {self.user_connections[recv_data[1]].getRooms()}',
                                       'Server', '', 'TEXT_MESSAGE'))
                    elif command[1] == 'leave':  # 离开聊天室
                        self.log(f'{recv_data[1]} wants to leave room {room_name}')
                        if room_name in self.chatting_rooms:
                            for name, user in self.user_connections.items():
                                if name == recv_data[1]:
                                    user.removeRoom(room_name)
                                    sock.send(pack(f'你已成功退出聊天室 {room_name}。', 'Server', '', 'TEXT_MESSAGE'))
                        else:
                            self.log(f'Room {room_name} does not exist, abort leaving.')
                            sock.send(pack(f'{room_name} 不存在，无法退出。', 'Server', '', 'TEXT_MESSAGE'))
                    elif command[1] == 'delete':  # 删除聊天室，需要Manager以上权限
                        self.log(f'{recv_data[1]} wants to delete room {room_name}')
                        if self.user_connections[recv_data[1]].getPermission() == 'Admin':
                            if room_name in self.chatting_rooms:
                                self.chatting_rooms.remove(room_name)
                                self.log(f'Room {room_name} deleted.')
                                for user in self.user_connections.values():
                                    if room_name in user.getRooms():
                                        user.removeRoom(room_name)
                                        user.getSocket().send(pack(f'{room_name} 聊天室已被管理员删除，已自动退出本聊天室。',
                                                                   'Server', '', 'TEXT_MESSAGE'))
                                    sock.send(pack(f'Room {room_name} deleted.', 'Server', '', 'TEXT_MESSAGE'))
                            else:
                                self.log(f'Room {room_name} does not exist, abort deleting.')
                                sock.send(pack(f'{room_name} 不存在，无法删除。', 'Server', '', 'TEXT_MESSAGE'))
                        else:
                            self.log(f'{recv_data[1]} do not have the permission to delete {room_name}.')
                            sock.send(pack(f'你没有权限删除聊天室 {room_name}。',
                                           'Server', '', 'TEXT_MESSAGE'))
                    time.sleep(0.0005)
                    sock.send(pack(json.dumps(self.user_connections[recv_data[1]].getRooms()),
                                   'Server', '', 'ROOM_MANIFEST'))

                elif command[0] == 'manager':  # 维护者任免命令
                    # command添加空格
                    operate_user = command[2]
                    if self.user_connections[recv_data[1]].getPermission() == 'Admin':
                        if command[1] == 'add':
                            self.log(f'{recv_data[1]} wants to add {operate_user} to the Manager group.')
                            if operate_user in self.user_connections and \
                                    self.user_connections[operate_user].getPermission() == 'User':
                                self.user_connections[operate_user].setPermission('Manager')
                                self.log(f'{operate_user} permission changed to Manager.')
                                self.user_connections[operate_user].getSocket().send(
                                    pack(f'你已被最高管理员添加为维护者。', 'Server', '', 'TEXT_MESSAGE')
                                )
                                sock.send(pack(f'{operate_user} permission changed to Manager.', 'Server', '',
                                               'TEXT_MESSAGE'))
                            else:
                                sock.send(pack(f'{operate_user} does not exist or has a higher permission, '
                                               f'abort prompting.', 'Server', '', 'TEXT_MESSAGE'))
                        elif command[1] == 'delete':
                            self.log(f'{recv_data[1]} wants to delete {operate_user} from the Manager group.')
                            if operate_user in self.user_connections and \
                                    self.user_connections[operate_user].getPermission() == 'Manager':
                                self.user_connections[operate_user].setPermission('User')
                                self.log(f'{operate_user} permission changed to User.')
                                self.user_connections[operate_user].getSocket().send(
                                    pack(f'你已被最高管理员撤掉维护者。', 'Server', '', 'TEXT_MESSAGE')
                                )
                                sock.send(pack(f'{operate_user} permission changed to User.', 'Server', '',
                                               'TEXT_MESSAGE'))
                            else:
                                sock.send(pack(f'{operate_user} does not exist or has a higher permission, '
                                               f'abort removing.', 'Server', '', 'TEXT_MESSAGE'))
                        elif command[1] == 'list':
                            self.log(f'{recv_data[1]} wants to list all managers.')
                            sock.send(pack(json.dumps(self.getManagers()), 'Server', '', 'MANAGER_LIST'))
                    else:
                        if command[1] == 'list':
                            self.log(f'{recv_data[1]} wants to list all managers.')
                            sock.send(pack(json.dumps(self.getManagers()), 'Server', '', 'MANAGER_LIST'))
                        else:
                            self.log(f'{recv_data[1]} do not have the permission to manage users.')
                            sock.send(pack(f'你没有最高权限以用于管理用户。', 'Server', '', 'TEXT_MESSAGE'))

                elif command[0] == 'kick':
                    self.log(f'{recv_data[1]} wants to kick {command[1]}.')
                    if self.user_connections[recv_data[1]].getPermission() != 'User':
                        if command[1] in self.user_connections and \
                                self.user_connections[command[1]].getPermission() == 'User':
                            self.user_connections[command[1]].getSocket().send(pack(
                                f'你已被管理员踢出服务器。', 'Server', '', 'TEXT_MESSAGE'))
                            self.closeConnection(self.user_connections[command[1]].getSocket(),
                                                 self.user_connections[command[1]].getAddress())
                            self.log(f'{command[1]} kicked.')
                            sock.send(pack(f'{command[1]} kicked.', 'Server', '', 'TEXT_MESSAGE'))
                        else:
                            if recv_data[1] == command[1]:
                                self.log(f'{recv_data[1]} tried to kick himself.')
                                sock.send(pack(f'You cannot kick yourself!!!', 'Server', '', 'TEXT_MESSAGE'))
                                for sending_sock in self.user_connections.values():  # 直接发送
                                    sending_sock.getSocket().send(pack(f'[新闻] 人类迷惑行为: {recv_data[1]} 试图把自己踢出服务器。',
                                                                       'Server', '', 'TEXT_MESSAGE'))
                            else:
                                self.log(f'{command[1]} does not exist, abort kicking.')
                                sock.send(pack(f'{command[1]} does not exist or is a Manager, abort kicking.',
                                               'Server', '', 'TEXT_MESSAGE'))
                    else:
                        self.log(f'{recv_data[1]} do not have the permission to kick {command[1]}.')
                        sock.send(pack(f'You do not have the permission to kick {command[1]}.',
                                       'Server', '', 'TEXT_MESSAGE'))

                elif command[0] == 'update':  # 有的用户可能无法及时更新用户列表，所以可以手动更新
                    self.log(f'{recv_data[1]} wants to update his user manifest manually.')
                    sock.send(pack(json.dumps(self.getOnlineUsers()), 'Server', self.default_room, 'USER_MANIFEST'))
                    time.sleep(0.0005)
                    sock.send(pack('你已成功更新用户列表。', 'Server', '', 'TEXT_MESSAGE'))

                elif command[0] == 'user':  # 用户系统相关命令
                    self.log(f'{recv_data[1]} wants to operate the SQL database.')
                    if self.user_connections[recv_data[1]].getPermission() == 'Admin':
                        if command[1] == 'create':  # 创建用户
                            self.log(f'{recv_data[1]} wants to create {command[2]}.')
                            if command[2] not in self.sql_exist_user and \
                                    command[2] not in self.user_connections and \
                                    command[2] != 'Server':
                                self.sql_cursor.execute('INSERT INTO USERS (USER_NAME, PASSWORD, PERMISSION, BAN) '
                                                        'VALUES (?, ?, ?, ?)',
                                                        (command[2],
                                                         hashlib.md5((" ".join(command[4:])).encode()).hexdigest(),
                                                         command[3], 0))
                                self.sql_connection.commit()
                                self.sql_exist_user.append(command[2])
                                self.log(f'{command[2]} created, permission: {command[3]}.')
                                sock.send(pack(f'{command[2]} created, permission: {command[3]}.',
                                               'Server', '', 'TEXT_MESSAGE'))
                            else:
                                self.log(f'{command[2]} already exists.')
                                sock.send(pack(f'{command[2]} already exists.', 'Server', '', 'TEXT_MESSAGE'))

                        elif command[1] == 'setpwd':  # 设置密码
                            self.log(f'{recv_data[1]} wants to set password of {command[2]}.')
                            if command[2] in self.sql_exist_user:
                                self.sql_cursor.execute('UPDATE USERS SET PASSWORD = ? WHERE USER_NAME = ?',
                                                        (hashlib.md5((" ".join(command[3:])).encode()).hexdigest(),
                                                         command[2]))
                                self.sql_connection.commit()
                                if command[2] in self.user_connections:
                                    self.user_connections[command[2]].getSocket().send(pack(
                                        f'你的密码已被更改为 {" ".join(command[3:])}。', 'Server', '', 'TEXT_MESSAGE'))
                                sock.send(pack(f'{command[2]} password set.', 'Server', '', 'TEXT_MESSAGE'))
                            else:
                                self.log(f'{command[2]} does not exist.')
                                sock.send(pack(f'{command[2]} does not exist.', 'Server', '', 'TEXT_MESSAGE'))

                        elif command[1] == 'setper':  # 设置权限
                            self.log(f'{recv_data[1]} wants to set permission of {command[2]}.')
                            if command[2] == 'root':
                                self.log(f'{recv_data[1]} tried to set permission of root.')
                                sock.send(pack(f'You cannot set the permission of root.',
                                               'Server', '', 'TEXT_MESSAGE'))
                            elif command[2] in self.sql_exist_user:
                                self.sql_cursor.execute('UPDATE USERS SET PERMISSION = ? WHERE USER_NAME = ?',
                                                        (command[3], command[2]))
                                self.sql_connection.commit()
                                if command[2] in self.user_connections:
                                    self.user_connections[command[2]].setPermission(command[3])
                                    self.user_connections[command[2]].getSocket().send(pack(
                                        f'你的权限已被更改为 {command[3]}。', 'Server', '', 'TEXT_MESSAGE'))
                                sock.send(pack(f'Successfully changed {command[2]} permission to {command[3]}。',
                                               'Server', '', 'TEXT_MESSAGE'))
                            else:
                                self.log(f'{command[2]} does not exist.')
                                sock.send(pack(f'{command[2]} does not exist.', 'Server', '', 'TEXT_MESSAGE'))

                        elif command[1] == 'delete':  # 删除用户
                            self.log(f'{recv_data[1]} wants to delete {command[2]}.')
                            # 查看数据库中要删除的用户的权限
                            self.sql_cursor.execute('SELECT PERMISSION FROM USERS WHERE USER_NAME = ?', (command[2],))
                            temp_permission = self.sql_cursor.fetchone()
                            if temp_permission:
                                permission = temp_permission[0]
                            else:
                                permission = 'User'
                            if recv_data[1] == command[2] or command[2] == 'root':
                                self.log(f'{recv_data[1]} tried to ban himself.')
                                sock.send(pack(f'You cannot delete yourself or root.',
                                               'Server', '', 'TEXT_MESSAGE'))
                            elif permission == 'Admin' and recv_data[1] != 'root':
                                self.log(f'{command[2]} cannot be deleted.')
                                sock.send(pack(f'{command[2]} is an administrator, only root can delete him.',
                                               'Server', '', 'TEXT_MESSAGE'))
                            elif command[2] in self.sql_exist_user:
                                self.sql_cursor.execute('DELETE FROM USERS WHERE USER_NAME = ?', (command[2],))
                                self.sql_connection.commit()
                                if command[2] in self.user_connections:
                                    self.user_connections[command[2]].getSocket().send(pack(
                                        f'你已被管理员踢出服务器。', 'Server', '', 'TEXT_MESSAGE'))
                                    self.closeConnection(self.user_connections[command[2]].getSocket(),
                                                         self.user_connections[command[2]].getAddress())
                                self.sql_exist_user.remove(command[2])
                                sock.send(pack(f'{command[2]} deleted', 'Server', '', 'TEXT_MESSAGE'))
                            else:
                                self.log(f'{command[2]} does not exist.')
                                sock.send(pack(f'{command[2]} does not exist', 'Server', '', 'TEXT_MESSAGE'))

                        elif command[1] == 'ban':  # 封禁用户
                            self.log(f'{recv_data[1]} wants to ban {command[2]}')
                            self.sql_cursor.execute('SELECT PERMISSION FROM USERS WHERE USER_NAME = ?', (command[2],))
                            permission = self.sql_cursor.fetchone()
                            if permission:
                                permission = permission[0]
                            else:
                                self.log(f'{command[2]} does not exist.')
                                sock.send(pack(f'{command[2]} does not exist', 'Server', '', 'TEXT_MESSAGE'))
                                return
                            if recv_data[1] == command[2] or command[2] == 'root':
                                self.log(f'{recv_data[1]} tried to ban himself.')
                                sock.send(pack(f'You cannot ban yourself or root.',
                                               'Server', '', 'TEXT_MESSAGE'))
                            elif permission == 'Admin' and recv_data[1] != 'root':
                                self.log(f'{command[2]} cannot be deleted.')
                                sock.send(pack(f'{command[2]} is an administrator, only root can ban him.',
                                               'Server', '', 'TEXT_MESSAGE'))
                            elif command[2] in self.sql_exist_user:
                                self.sql_cursor.execute('UPDATE USERS SET BAN = ? WHERE USER_NAME = ?', (1, command[2]))
                                self.sql_connection.commit()
                                if command[2] in self.user_connections:
                                    self.user_connections[command[2]].getSocket().send(pack(
                                        f'你已被管理员踢出服务器。', 'Server', '', 'TEXT_MESSAGE'))
                                    self.closeConnection(self.user_connections[command[2]].getSocket(),
                                                         self.user_connections[command[2]].getAddress())
                                sock.send(pack(f'{command[2]} banned.', 'Server', '', 'TEXT_MESSAGE'))
                            else:
                                self.log(f'{command[2]} does not exist.')
                                sock.send(pack(f'{command[2]} does not exist', 'Server', '', 'TEXT_MESSAGE'))

                        elif command[1] == 'restore':  # 解封用户
                            self.log(f'{recv_data[1]} wants to restore {command[2]}')
                            if command[2] in self.sql_exist_user:
                                self.sql_cursor.execute('UPDATE USERS SET BAN = ? WHERE USER_NAME = ?', (0, command[2]))
                                self.sql_connection.commit()
                                self.sql_exist_user.append(command[2])
                                sock.send(pack(f'{command[2]} unbanned.', 'Server', '', 'TEXT_MESSAGE'))
                            else:
                                self.log(f'{command[2]} does not exist.')
                                sock.send(pack(f'{command[2]} does not exist.', 'Server', '', 'TEXT_MESSAGE'))

                        else:
                            self.log(f'{command[1]} is not a valid operation.')
                            sock.send(pack(f'{command[1]} is not a valid operation.', 'Server', '', 'TEXT_MESSAGE'))

                elif command[0] == 'option':  # 服务器管理设置
                    if command[1] == 'show':
                        self.log(f'{recv_data[1]} checked the server options.')
                        sock.send(pack(f'Server Management Settings\n'
                                       f'logable: {self.logable}\n'
                                       f'recordable: {self.recordable}\n'
                                       f'forceAccount: {self.force_account}\n'
                                       f'allowRegister: {self.allow_register}',
                                       'Server', '', 'TEXT_MESSAGE'))
                    elif command[1] == 'set':
                        self.log(f'{recv_data[1]} tried to set {command[2]} to {command[3]}')
                        vaild_option = True
                        if command[2] == 'logable':
                            self.logable = (command[3] == 'true')
                        elif command[2] == 'recordable':
                            self.recordable = (command[3] == 'true')
                        elif command[2] == 'forceAccount':
                            self.force_account = (command[3] == 'true')
                        elif command[2] == 'allowRegister':
                            self.allow_register = (command[3] == 'true')
                        else:
                            vaild_option = False

                        sock.send(pack(f'Option {command[2]} has been set to {command[3] == "true"}'
                                       if vaild_option  # 如果选项有效，则发送上面的句子，反之发送下面的
                                       else
                                       f'Option {command[2]} not found, please check typing.',
                                       'Server', '', 'TEXT_MESSAGE'))

                elif command[0] == 'resetpwd':  # 自助重置密码
                    self.log(f'{recv_data[1]} wants to reset password.')
                    if not command[1]:
                        self.log(f'{recv_data[1]} tried to reset password without a password.')
                        sock.send(pack(f'Password needed!', 'Server', '', 'TEXT_MESSAGE'))
                    elif recv_data[1] in self.sql_exist_user:
                        self.sql_cursor.execute('UPDATE USERS SET PASSWORD = ? WHERE USER_NAME = ?',
                                                (hashlib.md5((" ".join(command[1:])).encode()).hexdigest(),
                                                 recv_data[1]))
                        self.sql_connection.commit()
                        sock.send(pack(f'Successfully changed the password to {" ".join(command[1:])}',
                                       'Server', '', 'TEXT_MESSAGE'))
                    else:
                        self.log(f'{recv_data[1]} does not exist.')
                        sock.send(pack(f'{recv_data[1]} 不存在于数据库，无法重置密码。', 'Server', '', 'TEXT_MESSAGE'))

                else:
                    sock.send(pack(f'{recv_data[2]} is not a valid command.', 'Server', '', 'TEXT_MESSAGE'))

            except IndexError:
                self.log(f'There is something wrong with {recv_data[1]} command.')
                sock.send(pack(f'SyntaxError: {recv_data[2]}', 'Server', '', 'TEXT_MESSAGE'))

        elif recv_data[0] == 'DO_NOT_PROCESS':  # 如果收到的是一个无效的消息，则先尝试直接发送
            for sending_sock in self.user_connections.values():
                sending_sock.getSocket().send(message)

        elif recv_data[0] == 'USER_NAME':  # 如果是用户名
            threading.Thread(target=self.processNewLogin, args=(sock, address, recv_data[1])).start()

        elif recv_data[0] == 'REGISTER':  # 用户系统注册信息
            self.log(f'New register information received.')
            if not self.allow_register:  # 如果禁止注册新用户
                sock.send(bytes('failed\0', 'utf-8'))
                return
            try:
                user, passwd = recv_data[1].split('\r\n')
            except ValueError:
                self.log('This is not a valid register information.')
                sock.send(bytes('failed\0', 'utf-8'))
                self.closeConnection(sock, address)
                return
            if passwd:
                if user in self.user_connections:
                    self.log(f'{user} tried to register again.')
                    sock.send(bytes('failed\0', 'utf-8'))  # 注册信息无法重复
                    self.closeConnection(sock, address)
                    return
            else:
                self.log(f'{user} tried to register without password.')
                sock.send(bytes('failed\0', 'utf-8'))  # 如果没有密码，则返回失败
                self.closeConnection(sock, address)
                return
            if user in self.sql_exist_user:
                self.log(f'{user} is already in the database.')
                sock.send(bytes('failed\0', 'utf-8'))  # 如果用户已存在，则返回失败
                self.closeConnection(sock, address)
                return
            elif user == 'Server':
                self.log(f'{user} tried to register as Server.')
                sock.send(bytes('failed\0', 'utf-8'))  # 不允许注册为Server
                self.closeConnection(sock, address)
                return
            else:
                self.sql_cursor.execute('INSERT INTO USERS (USER_NAME, PASSWORD, PERMISSION, BAN) VALUES (?, ?, ?, ?)',
                                        (user, passwd, 'User', 0))
                self.sql_connection.commit()
                self.sql_exist_user.append(user)
                self.log(f'{user} has been registered.')
                sock.send(bytes('successful\0', 'utf-8'))  # 注册成功
                self.closeConnection(sock, address)

    def processNewLogin(self, sock, address, user_info):
        """处理新登录的客户端"""
        try:
            user, passwd = user_info.split('\r\n')  # 分割用户名和密码
        except ValueError:
            user = user_info.strip()
            passwd = ''
        if passwd:
            if user in self.user_connections:
                self.log(f'{user} tried to login again.')
                sock.send(pack(f'请不要重复登录。', 'Server', '', 'TEXT_MESSAGE'))
                self.closeConnection(sock, address)
                return
            try:
                self.sql_cursor.execute('SELECT * FROM USERS WHERE USER_NAME = ? AND PASSWORD = ?', (user, passwd))
            except sqlite3.OperationalError:
                self.log(f'{user} tried to login with a wrong password.')
                sock.send(pack(f'用户名或密码错误。', 'Server', '', 'TEXT_MESSAGE'))
                self.closeConnection(sock, address)
                return
            else:
                # 暂时保存查询信息
                query_result = self.sql_cursor.fetchone()

            if not query_result:
                self.log(f'{user} tried to login with a wrong password.')
                sock.send(pack(f'用户名或密码错误。', 'Server', '', 'TEXT_MESSAGE'))
                self.closeConnection(sock, address)
                return
            else:
                logged_user = True
        elif self.force_account:
            self.log(f'{user} tried to login without password.')
            sock.send(pack('该服务器启用了强制用户系统，请使用帐号登录。', 'Server', '', 'TEXT_MESSAGE'))
            self.closeConnection(sock, address)
            return
        elif user in self.sql_exist_user:
            self.log(f'{user} is already in the database.')
            sock.send(pack(f'该用户名已存在。', 'Server', '', 'TEXT_MESSAGE'))
            self.closeConnection(sock, address)
            return
        elif user == 'Server':
            self.log(f'{user} tried to login as Server.')
            sock.send(pack(f'该用户名已存在。', 'Server', '', 'TEXT_MESSAGE'))
            self.closeConnection(sock, address)
            return
        else:
            logged_user = False
            query_result = ('' for _ in range(6))

        if query_result[3]:
            self.log(f'{user} is banned.')
            sock.send(pack(f'你已被管理员封禁。', 'Server', '', 'TEXT_MESSAGE'))
            self.closeConnection(sock, address)
            return

        new_port = str(address[1])
        sock.send(pack(self.default_room, '', '', 'DEFAULT_ROOM'))  # 发送默认群聊
        if user == '用户名不存在' or not user:  # 如果客户端未设定用户名
            user = address[0] + ':' + new_port  # 直接使用IP和端口号
        while user in self.chatting_rooms:  # 如果用户名已经存在
            user += new_port  # 用户名和端口号
        user = user[:20].strip()  # 如果用户名过长，则截断并去除首尾空格
        for client in self.user_connections.values():
            if client.getUserName() == user:  # 如果重名，则添加数字（端口不会重复）
                user += new_port
            # 将用户名加入连接列表

        # User类的实例化参数: conn, address, permission, passwd, id_num, name
        if logged_user and query_result:
            # 用数据库的信息初始化User类
            self.user_connections[user] = \
                User(sock, address, query_result[2], self.client_id, user)
        else:
            self.user_connections[user] = \
                User(sock, address, 'User', self.client_id, user)  # 将用户名和连接加入连接列表

        online_users = self.getOnlineUsers()  # 获取在线用户
        time.sleep(0.2)  # 等待一下，否则可能会出现粘包
        for sending_sock in self.user_connections.values():  # 开始发送用户列表
            sending_sock.getSocket().send(pack(json.dumps(online_users), '', self.default_room, 'USER_MANIFEST'))
        self.log(f"{user} logged in.")
        return

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
            sending_sock.getSocket().send(pack(json.dumps(online_users), '', self.default_room, 'USER_MANIFEST'))
        sock.close()

    def log(self, content: str, end='\n', show_time=True):
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
        if self.logable:
            with open(f'logs/lhat_server{time.strftime("%Y-%m-%d", time.localtime())}.log', 'a') as f:
                f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}] {content}{end}')

    def record(self, message):
        """
        记录聊天消息
        :param message: 记录内容
        :return: 无返回值
        """
        print(message)
        if self.recordable:
            with open('records/lhat_chatting_record.txt', 'a') as f:
                if isinstance(message, str):
                    f.write(message + '\n')
                elif isinstance(message, bytes):
                    f.write(message.decode('utf-8') + '\n')


if __name__ == '__main__':
    server = Server()  # 创建一个服务器对象
    server.run()  # 启动服务器

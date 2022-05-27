import re
import socket
import selectors  # IO多路复用
import os
import sys
import json
import types

from server_operations import *
import settings  # 导入配置文件


ip = settings.ip_address
port = settings.network_port
default_room = settings.default_chatting_room
password = settings.password


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

    def setPermission(self, permission, passwd):
        """
        设置客户端的权限
        """
        if password == passwd:
            self.__permission = permission
            self._socket.send(pack(f'权限更改为{permission}', default_room, self._username, 'Server'))
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


class Server:
    """
    服务器类，用于接收客户端的请求，并调用相应的操作
    """
    def __init__(self):
        """
        初始化服务器
        """
        self.log('=====NEW SERVER INITIALIZING BELOW=====', show_time=False)
        self.user_connections = {}  # 创建一个空的用户连接列表
        self.need_handle_messages = []  # 创建一个空的消息队列
        self.chatting_rooms = [default_room]  # 创建一个聊天室列表
        self.client_id = 0  # 创建一个id，用于给每个连接分配一个id
        self.log('Initializing server... ', end='')
        self.select = selectors.DefaultSelector()  # 创建IO多路复用
        self.main_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # 创建socket
        self.log('Done!', show_time=False)
        self.log('Now the server can be ran.')

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
        self.log('  To change the ip address, \n  please visit settings.py')
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
            except ConnectionResetError:  # 如果读取失败，则说明客户端已断开连接
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
                time.sleep(0.0002)  # 粘包现象很恶心，sleep暂时能解决

    def processMessage(self, message: str, sock: socket.socket, address=None):
        """
        处理消息，让服务器决定如何处理
        :param message: 待处理的消息
        :param sock: 客户端连接
        :param address: 客户端地址
        :return: 无返回值
        """
        if not message:  # 客户端发送了空消息，于是直接断连
            self.log(f'Connection closed: {address[0]}:{address[1]}')
            self.select.unregister(sock)  # 从IO多路复用中移除连接
            sock.close()  # 关闭连接
            return
        recv_data = unpack(message)  # 解码消息
        if recv_data[0] == 'TEXT_MESSAGE' or recv_data[0] == 'FILE_RECV_DATA':  # 如果能正常解析，则进行处理
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
        elif recv_data[0] == 'DO_NOT_PROCESS':
            for sending_sock in self.user_connections.values():
                sending_sock.getSocket().send(message)

        elif recv_data[0] == 'USER_NAME':  # 如果是用户名
            sock.send(pack(default_room, None, None, 'DEFAULT_ROOM'))  # 发送默认群聊
            if recv_data[1] == '用户名不存在':  # 如果客户端未设定用户名
                user = address[0] + ':' + address[1]  # 直接使用IP和端口号
            elif recv_data[1] in self.chatting_rooms:  # 如果用户名已经存在
                user = recv_data[1] + ':' + address[1]  # 用户名和端口号
            else:
                user = recv_data[1]  # 否则使用客户端设定的用户名
            user = user[:20]  # 如果用户名过长，则截断
            for client in self.user_connections.values():
                if client.getUserName() == user:  # 如果重名，则添加数字
                    user += address[1]
                # 将用户名加入连接列表

            # conn, address, permission, passwd, id_num
            self.user_connections[self.client_id] = \
                User(sock, address, 'User', '123456', self.client_id, user)  # 将用户名和连接加入连接列表
            self.client_id += 1

            online_users = self.getOnlineUsers()  # 获取在线用户
            time.sleep(0.0005)  # 等待一下，否则可能会出现粘包
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
        with open('lhat_server.log', 'a') as f:
            f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}] {content}{end}')

    @staticmethod
    def record(message):
        """
        记录
        :param message: 记录内容
        :return: 无返回值
        """
        print(message)
        with open('lhat_chatting_record.txt', 'a') as f:
            f.write(message.decode('utf-8') + '\n')


if __name__ == '__main__':
    server = Server()  # 创建一个服务器对象
    server.run()  # 启动服务器

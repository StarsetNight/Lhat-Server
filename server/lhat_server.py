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


class Server:
    """
    服务器类，用于接收客户端的请求，并调用相应的操作
    """
    def __init__(self):
        """
        初始化服务器
        """
        self.select = selectors.DefaultSelector()  # 创建IO多路复用
        self.main_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # 创建socket
        # main_sock是用于监听的socket，用于接收客户端的连接
        self.main_sock.bind((ip, port))
        self.main_sock.listen(20)  # 监听，最多accept 20个连接数
        print(f'Running server on {ip}:{port}')
        print('  To change the ip address, \n  please visit settings.py')
        print('Waiting for connection...')
        self.main_sock.setblocking(False)  # 设置为非阻塞
        self.need_handle_messages = []  # 创建一个空的消息队列
        self.user_connections = {}  # 创建一个空的用户连接列表
        self.select.register(self.main_sock, selectors.EVENT_READ, data=None)  # 注册socket到IO多路复用，以便于多连接

    def run(self):
        """
        启动服务器
        :return: 无返回值，因为服务器一直运行，直到程序结束
        """
        while True:
            events = self.select.select(timeout=None)  # 阻塞等待IO事件
            for key, mask in events:  # 事件循环，key用于获取连接，mask用于获取事件类型
                if key.data is None:  # 如果是新连接
                    self.createConnection(key.fileobj)  # 接收连接
                else:  # 如果是已连接
                    self.serveClient(key, mask)  # 处理连接
            time.sleep(0.0001)  # 因为是阻塞的，所以sleep不会漏消息，同时降低负载

    def createConnection(self, sock):
        """
        创建一个新连接
        :param sock: 创建的socket对象
        :return: 无返回值
        """
        conn, address = sock.accept()  # 接收连接，并创建一个新的连接
        print(f'Connection established: {address[0]}:{address[1]}')
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
                print(f'Connection closed: {data.address[0]}:{data.address[1]}')
                self.select.unregister(sock)  # 从IO多路复用中移除连接
                temp_connections = self.user_connections.copy()
                for username, exist_socks in temp_connections.items():
                    if exist_socks == sock:
                        del self.user_connections[username]
                online_users = self.getOnlineUsers()
                for sending_sock in self.user_connections.values():
                    sending_sock.send(pack(json.dumps(online_users), None, 'Lhat! Chatting Room', 'USER_MANIFEST'))
                sock.close()  # 关闭连接
                return
            if data.inbytes:
                self.need_handle_messages.append(data.inbytes)
                data.inbytes = b''
            else:
                print(f'Connection closed: {data.address[0]}:{data.address[1]}')
                self.select.unregister(sock)  # 如果没有消息，则从IO多路复用中移除连接
                for username, exist_socks in self.user_connections.items():
                    if exist_socks == sock:
                        del self.user_connections[username]
                online_users = self.getOnlineUsers()
                for sending_sock in self.user_connections.values():
                    sending_sock.send(pack(json.dumps(online_users), None, 'Lhat! Chatting Room', 'USER_MANIFEST'))
                sock.close()
                return

        if mask & selectors.EVENT_WRITE:  # 如果可写，向客户端发送消息
            if self.need_handle_messages:
                for processing_message in self.need_handle_messages:
                    self.processMessage(processing_message, sock, data.address)
                self.need_handle_messages = []

    def processMessage(self, message, sock, address=None):
        """
        处理消息，让服务器决定如何处理
        :param message: 待处理的消息
        :param sock: 客户端连接
        :param address: 客户端地址
        :return: 无返回值
        """
        if not message:
            print(f'Connection closed: {address[0]}:{address[1]}')
            self.select.unregister(sock)  # 从IO多路复用中移除连接
            sock.close()  # 关闭连接
            return
        recv_data = unpack(message.decode('utf-8'))  # 解码消息
        if recv_data[0] == 'TEXT_MESSAGE' or recv_data[0] == 'FILE_RECV_DATA':  # 如果能正常解析，则进行处理
            if recv_data[1] == 'Lhat! Chatting Room':  # 群聊
                print(message)
                for sending_sock in self.user_connections.items():  # 直接发送
                    sending_sock[1].send(message)
            else:
                print(f'Private Message received [{recv_data[3]}]')
                for username, sending_sock in self.user_connections.items():  # 私聊
                    if username == recv_data[1] or username == recv_data[2]:  # 遍历所有用户，找到对应用户
                        # 第一个表达式很好理解，发给谁就给谁显示，第二个表达式则是自己发送，但是也得显示给自己
                        sending_sock.send(message)  # 发送给该用户
        elif recv_data[0] == 'DO_NOT_PROCESS':
            for sending_sock in self.user_connections.items():
                sending_sock[1].send(message)

        elif recv_data[0] == 'USER_NAME':  # 如果是用户名
            if recv_data[1] == '用户名不存在':  # 如果客户端未设定用户名
                user = address[0] + ':' + address[1]  # 直接使用IP和端口号
            else:
                user = recv_data[1]  # 否则使用客户端设定的用户名
            tag = 0
            for username in self.user_connections.keys():
                if username == user:  # 如果重名，则添加数字
                    tag += 1
                    user = user + str(tag)
                # 将用户名加入连接列表
            self.user_connections[user] = sock
            online_users = self.getOnlineUsers()
            for sending_sock in self.user_connections.values():
                sending_sock.send(pack(json.dumps(online_users), None, 'Lhat! Chatting Room', 'USER_MANIFEST'))

    def getOnlineUsers(self):
        """
        获取在线用户
        :return: 在线用户列表
        """
        online_users = []
        for user in self.user_connections.keys():
            online_users.append(user)
        return online_users


if __name__ == '__main__':
    server = Server()  # 创建一个服务器对象
    server.run()  # 启动服务器

import os


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
        self._connection = conn
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
            self._connection.send(bytes('exists\0', 'utf-8'))
            self._connection.close()
        else:
            with open(self.file_path, 'wb') as f:
                try:
                    data = self._connection.recv(1024)
                except ConnectionResetError:
                    print(f'File Client {self.address} disconnected.')
                    data = b''
                while data:
                    f.write(data)
                    try:
                        data = self._connection.recv(1024)
                    except ConnectionResetError:
                        print(f'File Client {self.address} disconnected.')
                        break
            self._connection.send(bytes('successful\0', 'utf-8'))
            self._connection.close()
            file_list[self.file_id] = self.file_path

    def startSend(self, recv_id, file_list):
        if recv_id in file_list:
            with open(file_list[recv_id], 'rb') as f:
                data = f.read(1024)
                while data:
                    if data == b'':
                        break
                    self._connection.send(data)
                    data = f.read(1024)
            self._connection.close()
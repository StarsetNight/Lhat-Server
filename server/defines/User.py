from defines.settings import password, default_room, root_password


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

    def setPermission(self, permission='User', passwd=''):
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

    def getSocket(self):
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

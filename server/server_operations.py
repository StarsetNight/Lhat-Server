import json
import time


def pack(raw_message, send_from, chat_with, message_type, file_name=None):
    """
    打包消息，用于发送
    :param raw_message: 正文消息
    :param send_from: 发送者
    :param chat_with: 聊天对象
    :param message_type: 消息类型
    :param file_name: 文件名，如果不是文件类型，则为None
    """
    message = {
        'by': send_from,
        'to': chat_with,
        'type': message_type,
        'time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())),
        'message': raw_message,
        'file': file_name,
        'end': 'JSON_MESSAGE_END'
    }  # 先把收集到的信息存储到字典里
    return json.dumps(message).encode('utf-8')  # 再用json打包


def unpack(json_message: str):
    """
    解包消息，用于接收JSON格式的消息
    看不懂message字典对应的东西吗？message_types里面有。

    :param json_message: JSON消息
    :return: 返回的东西有很多，也有可能是报错
    ==================================================
    return返回值大全：
    JSON_MESSAGE_NOT_EOF: 消息不完整
    NOT_JSON_MESSAGE: 不是JSON格式的消息
    MANIFEST_NOT_JSON: 用户名单不是JSON格式
    UNKNOWN_MESSAGE_TYPE: 未知消息类型
    --------------------------------------------------
    FILE_SAVED: 文件保存成功
    <一个列表>: 这是用户名单，有用的
    """
    try:
        message = json.loads(json_message)
        if isinstance(message, list):
            message = message[0]
            message = json.loads(message)
        elif isinstance(message, dict):
            pass

        if message['end'] != 'JSON_MESSAGE_END':
            return None
    except json.decoder.JSONDecodeError:
        return None

    if message['type'] == 'TEXT_MESSAGE_ARTICLE':  # 如果是纯文本消息
        return 'TEXT_MESSAGE'
    elif message['type'] == 'USER_NAME':  # 如果是用户名称
        try:
            username = message['message']
            return message['type'], username
        except json.decoder.JSONDecodeError:
            return 'MANIFEST_NOT_JSON'

    elif message['type'] == 'FILE_RECV_DATA':
        '''
        output_box.emit('锵锵！正在接收文件...')
        file_path = os.path.join('/files/', message['message'])
        with open(file_path, 'wb') as opened_file:
            opened_file.write(message['message'])
        output_box.emit(f'接收完毕！保存路径为：{file_path}')
        return 'FILE_SAVED'
        '''
        # 待办 接收文件
    else:
        return 'UNKNOWN_MESSAGE_TYPE'

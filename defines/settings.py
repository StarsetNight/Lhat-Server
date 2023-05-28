# coding = utf-8

# ABOUT

VERSION = "v1.6.0"  # Lhat Server版本

# SETTINGS

ip_address = '127.0.0.1'  # 服务器建立的ip地址，通常为localhost（127.0.0.1）
network_port = 8080  # 服务器的端口，内网穿透的时候要填写本地端口为此
default_room = 'Lhat! Chatting Room'  # 默认聊天室名称

log = True  # 是否记录日志
record = True  # 是否记录聊天记录
force_account = True  # 是否强制用户系统，为True时，游客无法加入聊天室，注意，游客模式不被提倡，建议禁用
allow_register = True  # 是否允许注册新用户，Manager权限以上可以在运行后更改
lock_server = False  # 为保证服务器通讯安全，可以锁定服务器，仅Admin权限用户可加入，但是已加入普通用户不会被踢出

# SQL COMMANDS

create_table = '''CREATE TABLE IF NOT EXISTS USERS(
USER_NAME VARCHAR(20) PRIMARY KEY NOT NULL,
PASSWORD CHAR(32) NOT NULL,
PERMISSION VARCHAR(8) NOT NULL,
BAN INTEGER NOT NULL
);'''

append_user = 'INSERT INTO USERS (USER_NAME, PASSWORD, PERMISSION, BAN) VALUES(?, ?, ?, ?)'

delete_user = 'DELETE FROM USERS WHERE USER_NAME = ?'

get_user_info = 'SELECT * FROM USERS WHERE USER_NAME = ?'

reset_user_password = 'UPDATE USERS SET PASSWORD = ? WHERE USER_NAME = ?'

set_permission = 'UPDATE USERS SET PERMISSION = ? WHERE USER_NAME = ?'

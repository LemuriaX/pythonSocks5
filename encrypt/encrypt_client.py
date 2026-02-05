import json
import socket
import struct
import threading

from encrypt.crypto_utils import GCMCipher

# 字符,C 类型,Python 类型,标准大小 (字节)
# b / B,char / unsigned char,int,1
# h / H,short / unsigned short,int,2
# i / I,int / unsigned int,int,4
# q / Q,long long / unsigned,int,8
# f,float,float,4
# d,double,float,8
# s,char[],bytes,指定长度

config = json.load(open('local_config.json', 'r'))
gcm_cipher = GCMCipher(config['password'])


def hexdump(data, length=16):
    filter = ''.join([(len(repr(chr(x))) == 3) and chr(x) or '.' for x in range(256)])
    lines = []
    for c in range(0, len(data), length):
        chars = data[c:c + length]
        hex = ' '.join(["%02x" % x for x in chars])
        printable = ''.join(["%s" % ((x <= 127 and filter[x]) or '.') for x in chars])
        lines.append("%04x  %-*s  %s" % (c, length * 3, hex, printable))
    print('\n'.join(lines))


# 处理握手
def handle_handshake(client_socket):
    # VER NMETHODS
    # 1   1
    ver, nmethods = client_socket.recv(2)
    if ver != 5:
        print("[-] Unsupported SOCKS version")
        return False
    methods = client_socket.recv(nmethods)
    print("[+] Client supported methods:", methods)
    if 0x00 not in set(methods):
        print("[-] No acceptable authentication methods")
        return False, None, None
    data = struct.pack('!BB', 5, 0)
    client_socket.sendall(data)

    return True, ver, nmethods


# 读取目标地址和端口
def get_target_addr_port(client_socket):
    buf = client_socket.recv(4)
    ver, cmd, rsv, atyp = struct.unpack('!BBBB', buf)
    addr = None
    if atyp == 1:  # IPv4
        data = client_socket.recv(4)
        addr = socket.inet_ntoa(data)
    elif atyp == 3:  # Domain name
        data = client_socket.recv(1)
        addr_len = ord(data)
        addr = client_socket.recv(addr_len).decode()
    port_data = client_socket.recv(2)
    port = struct.unpack('!H', port_data)[0]
    print(f"[+] Request: CMD={cmd}, ADDR={addr}, PORT={port}")
    return ver, cmd, rsv, atyp, addr, port


# 连接目标地址
def connect_target(addr, port):
    try:
        remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        remote.connect((addr, port))
        # 发送握手校验
        header, nonce, ciphertext = gcm_cipher.encrypt_packet(config['password'].encode())
        remote.sendall(header + nonce + ciphertext)
        print("[+] Sent handshake verification to remote server")
        # 发送版本号、NMETHODS、METHODS
        remote.sendall(struct.pack("!BBB", 5, 1, 0))
        # 接收远程服务器的连接响应
        response = remote.recv(2)
        print(f"[+] Remote server connect response:", response)
        return remote
    except Exception as e:
        print(f"[-] Connection to target {addr}:{port} failed: {e}")
        return None


# 转发local发来的请求到remote
def local_forward(local_socket, remote_socket):
    while True:
        try:
            data = local_socket.recv(4096)
            if not data:
                break
            # 加密数据
            header, nonce, ciphertext = gcm_cipher.encrypt_packet(data)
            # 发送数据到远程
            remote_socket.sendall(header + nonce + ciphertext)
        except ConnectionAbortedError:
            break
    local_socket.close()
    remote_socket.close()

def remote_forward(remote_socket, local_socket):
    while True:
        try:
            # 从远程接收数据
            header = remote_socket.recv(2)
            if not header:
                break
            length = struct.unpack('!H', header)[0]
            nonce = remote_socket.recv(12)
            ciphertext = remote_socket.recv(length - 12)
            try:
                data = gcm_cipher.decrypt_packet(nonce + ciphertext)
                local_socket.sendall(data)
            except Exception as e:
                print(f"[-] Decryption failed: {e}")
                break
        except ConnectionAbortedError:
            break
    local_socket.close()
    remote_socket.close()

# 转发目标地址和端口到远程服务器
def forward_target_addr_port_remote(local_socket, remote_socket):
    ver, cmd, rsv, atyp, addr, port = get_target_addr_port(local_socket)
    remote_socket.sendall(struct.pack("!BBBB", ver, cmd, rsv, atyp))
    if atyp == 1:  # IPv4
        remote_socket.sendall(socket.inet_aton(addr))
    elif atyp == 3:  # Domain name
        header, nonce, ciphertext = gcm_cipher.encrypt_packet(addr.encode())
        remote_socket.sendall(header + nonce + ciphertext)
    remote_socket.sendall(struct.pack("!H", port))


# 启动管道
def start_pipe(local_socket, remote_socket):
    forward_target_addr_port_remote(local_socket, remote_socket)
    # 服务器连接响应
    data = remote_socket.recv(10)
    _, connect_state, _, _, _, _ = struct.unpack("!BBBBIH", data)
    if connect_state != 0:
        # 远程服务器连接目标失败
        print("[-] Remote server Connection to target failed")
        data = struct.pack("!BBBBIH", 5, 1, 0, 1, 0, 0)
        local_socket.sendall(data)
        return
    data = struct.pack("!BBBBIH", 5, 0, 0, 1, 0, 0)
    local_socket.sendall(data)
    t1 = threading.Thread(target=local_forward, args=(local_socket, remote_socket))
    t2 = threading.Thread(target=remote_forward, args=(remote_socket, local_socket))
    t1.start()
    t2.start()


# 入口
def client_run(local_socket):
    remote_socket = None
    try:
        # 处理握手
        state, ver, nmethods = handle_handshake(local_socket)
        if not state:
            print("[-] Connection failed - Local Handshake failed")
            return

        # 获取目标地址和端口
        # target_addr, target_port = get_target_addr_port(local_socket)
        # target_socket = connect_target(local_socket, target_addr, target_port)
        # 连接到远程服务器
        remote_addr = config['remote_addr']
        remote_port = config['remote_port']
        remote_socket = connect_target(remote_addr, remote_port)
        if remote_socket:
            start_pipe(local_socket, remote_socket)
        local_socket = None
        remote_socket = None
    finally:
        if local_socket is not None:
            local_socket.close()
        if remote_socket is not None:
            remote_socket.close()


def main():
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    client.bind(('0.0.0.0', config.get("local_port", 8080)))

    client.listen()

    while True:
        local_socket, addr = client.accept()
        print(f"[+] Accepted connection from {addr[0]}:{addr[1]}")
        t = threading.Thread(target=client_run, args=(local_socket,))
        t.start()


if __name__ == '__main__':
    main()

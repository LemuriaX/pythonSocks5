import socket
import struct
import threading

import json

config = json.load(open('remote_config.json', 'r'))

# 字符,C 类型,Python 类型,标准大小 (字节)
# b / B,char / unsigned char,int,1
# h / H,short / unsigned short,int,2
# i / I,int / unsigned int,int,4
# q / Q,long long / unsigned,int,8
# f,float,float,4
# d,double,float,8
# s,char[],bytes,指定长度

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
        return False
    data = struct.pack('!BB', 5, 0)
    client_socket.sendall(data)
    return True


def handle_request(client_socket):
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
    return addr, port


def connect_target(client_socket, addr, port):
    try:
        remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        remote.connect((addr, port))
        data = struct.pack("!BBBBIH", 5, 0, 0, 1, 0, 0)
        client_socket.sendall(data)
        return remote
    except Exception as e:
        print(f"[-] Connection to target {addr}:{port} failed: {e}")
        data = struct.pack("!BBBBIH", 5, 1, 0, 1, 0, 0)
        client_socket.sendall(data)
        return None


def hexdump(data, length=16):
    filter = ''.join([(len(repr(chr(x))) == 3) and chr(x) or '.' for x in range(256)])
    lines = []
    for c in range(0, len(data), length):
        chars = data[c:c + length]
        hex = ' '.join(["%02x" % x for x in chars])
        printable = ''.join(["%s" % ((x <= 127 and filter[x]) or '.') for x in chars])
        lines.append("%04x  %-*s  %s" % (c, length * 3, hex, printable))
    print('\n'.join(lines))


def forward(client_socks, remote):
    while True:
        try:
            data = client_socks.recv(4096)
            # hexdump(data)
            if not data:
                break
            remote.sendall(data)
        except ConnectionAbortedError:
            break
    client_socks.close()
    remote.close()


def start_pipe(client_socket, remote):
    t1 = threading.Thread(target=forward, args=(client_socket, remote))
    t2 = threading.Thread(target=forward, args=(remote, client_socket))
    t1.start()
    t2.start()


def handle_client(local_socket):
    remote = None
    try:
        if not handle_handshake(local_socket):
            print("[-] Connection failed - Handshake failed")
            return
        addr, port = handle_request(local_socket)
        remote = connect_target(local_socket, addr, port)
        if remote:
            start_pipe(local_socket, remote)
        local_socket = None
        remote = None
    finally:
        if local_socket is not None:
            local_socket.close()
        if remote is not None:
            remote.close()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    remote_port = config.get("port")
    server.bind(('0.0.0.0', remote_port))

    server.listen()

    while True:
        local_socket, addr = server.accept()
        print(f"[+] Accepted connection from {addr[0]}:{addr[1]}")
        t = threading.Thread(target=handle_client, args=(local_socket,))
        t.start()


if __name__ == '__main__':
    main()

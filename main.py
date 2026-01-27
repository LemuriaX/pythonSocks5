import socket
import struct
import threading

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


def handle_client(client_socket):
    with client_socket:
        if not handle_handshake(client_socket):
            print("[-] Connection failed - Handshake failed")
            return
        handle_request(client_socket)

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', 10110))

    server.listen()

    while True:
        client_socket, addr = server.accept()
        print(f"[+] Accepted connection from {addr[0]}:{addr[1]}")
        t = threading.Thread(target=handle_client, args=(client_socket,))
        t.start()


if __name__ == '__main__':
    main()

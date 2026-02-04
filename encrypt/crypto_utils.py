import os
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class GCMCipher:
    def __init__(self, password_str):
        salt = b'y.fkrjuq7Dw!w2-gEbzwqi_ccmAroPZqZ8K*FX2pCTcB3BAofbhZnir4XKoZ8wMC'
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = kdf.derive(password_str.encode())

        self.aead = AESGCM(key)

    def encrypt_packet(self, plain_data):
        """
        封包格式：[2字节 长度] + [12字节 Nonce] + [密文 + Tag]
        """
        # 1. 生成唯一的 Nonce (12字节)
        nonce = os.urandom(12)

        # 2. 加密
        # 这里的 ciphertext 实际上包含了 = 纯密文 + Tag(16字节)
        ciphertext = self.aead.encrypt(nonce, plain_data, None)

        # 3. 计算总长度 (Nonce长 + 密文长)
        # 注意：这里的长度是发给 TCP 对端看的，方便它拆包
        total_len = len(nonce) + len(ciphertext)

        # 4. 拼装头部 [Length (2byte)]
        header = struct.pack('!H', total_len)
        # 5. 最终拼接
        return header, nonce, ciphertext

    def decrypt_packet(self, body_data):
        """
        输入的是去掉了 [Length] 头部之后的数据： [Nonce] + [Ciphertext]
        """
        if len(body_data) < 12 + 16:  # Nonce(12) + Tag(16)
            raise ValueError("数据包太短")

        # 1. 拆解 Nonce
        nonce = body_data[:12]
        encrypted_payload = body_data[12:]

        # 2. 解密 (如果你改了密文一个字节，这里会抛出 InvalidTag 异常)
        try:
            plain_data = self.aead.decrypt(nonce, encrypted_payload, None)
            return plain_data
        except Exception:
            raise Exception("解密失败：数据被篡改或密码错误")

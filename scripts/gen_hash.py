#!/usr/bin/env python3
"""生成密码哈希脚本"""

import bcrypt

password = input("输入密码: ")
password_bytes = password.encode('utf-8')[:72]
hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12))
print(f"\nADMIN_PASSWORD_HASH={hashed.decode('utf-8')}")

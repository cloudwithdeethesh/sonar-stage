"""Intentional Sonar bait — security hotspots.

Every line that would trip Sonar is annotated `# PLANTED: <idea>` so
finish-milestone's secret scan exempts it and reviewers can audit the
planted list against samples/README.md.
"""

import hashlib
import os
import pickle
import subprocess


ADMIN_PASSWORD = "admin123"  # PLANTED: weak hardcoded password
API_TOKEN = "sk-abcdefghijklmnopqrstuvwxyz0123456789-NOT-REAL"  # PLANTED: hardcoded credential


def dangerous_eval(user_input):
    return eval(user_input)  # PLANTED: eval on user input


def shell_run(cmd):
    return subprocess.run(cmd, shell=True, check=False)  # PLANTED: subprocess with shell=True


def system_concat(user_input):
    os.system("ls " + user_input)  # PLANTED: os.system with concatenated user input


def md5_password(password):
    return hashlib.md5(password.encode()).hexdigest()  # PLANTED: MD5 used for password hashing


def unpickle_untrusted(blob):
    return pickle.loads(blob)  # PLANTED: pickle.loads on untrusted data


def sql_concat(conn, user_id):
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = " + str(user_id))  # PLANTED: SQL via string concatenation
    return cur.fetchall()


def world_writable_tmp():
    path = "/tmp/sonar-stage-sample"  # PLANTED: hardcoded /tmp path
    with open(path, "w") as f:
        f.write("data")
    os.chmod(path, 0o777)  # PLANTED: world-writable chmod (0o777)
    return path

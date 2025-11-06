import requests
import configparser
import logging
import time
from threading import Thread, Event
from urllib.parse import quote
from requests.exceptions import ConnectionError, Timeout, RequestException
from flask import Flask, render_template, request, jsonify
from io import StringIO
import sys
import os
from pystray import Icon, MenuItem as item
from PIL import Image  # 用于加载图标

# 新增：用于停止Flask服务的事件
flask_stop_event = Event()

# 获取打包后的资源根目录
base_path = (
    sys._MEIPASS
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)

# 明确指定模板文件夹和静态文件夹
app = Flask(
    __name__,
    template_folder=os.path.join(base_path, "templates"),
    static_folder=os.path.join(base_path, "static"),
)

config_path = os.path.join(base_path, "config.ini")

# 全局变量
config = configparser.ConfigParser()
log_buffer = StringIO()  # 用于存储日志的缓冲区
is_running = True  # 程序运行状态
last_config_mtime = 0  # 记录配置文件最后修改时间
MAX_LOG_BUFFER_SIZE = 1024 * 1024  # 日志缓冲区最大1MB

logging.getLogger("werkzeug").setLevel(logging.WARNING)


# -------------------------- 1. 初始化配置 --------------------------
def load_config():
    """加载配置文件"""
    global config
    config.read(config_path, encoding="utf-8")
    return config


load_config()

# 核心配置
USERNAME = config["CAMPUS_NET"]["USERNAME"]
PASSWORD = config["CAMPUS_NET"]["PASSWORD"]
CHECK_INTERVAL = int(config["CAMPUS_NET"]["CHECK_INTERVAL"])
DETECT_URL = config["CAMPUS_NET"]["DETECT_URL"]
LOGIN_BASE_URL = config["CAMPUS_NET"]["LOGIN_BASE_URL"]

log_file = config["CAMPUS_NET"]["LOG_FILE"]
LOG_FILE = os.path.join(base_path, log_file)

# 状态检测特征
NOT_LOGGED_FLAG = config["DETECT_FLAG"]["NOT_LOGGED"]
LOGGED_SUCCESS_FLAG = config["DETECT_FLAG"]["LOGGED_SUCCESS"]
LOGIN_SUCCESS_FLAG = config["DETECT_FLAG"]["LOGIN_SUCCESS"]


# -------------------------- 2. 配置日志 --------------------------
class WebLogHandler(logging.Handler):
    """自定义日志处理器，限制缓冲区大小"""

    def emit(self, record):
        msg = self.format(record) + "\n"
        # 检查当前缓冲区大小
        current_size = log_buffer.tell()
        if current_size + len(msg) > MAX_LOG_BUFFER_SIZE:
            # 截断到保留最后500KB内容
            log_buffer.seek(0)
            content = log_buffer.read()
            new_content = content[-512000:]  # 保留最后500KB
            log_buffer.seek(0)
            log_buffer.truncate()
            log_buffer.write(new_content)
        log_buffer.write(msg)
        log_buffer.seek(0, 2)  # 移动到末尾


# 配置日志同时输出到文件、控制台和Web缓冲区
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
        WebLogHandler(),
    ],
)
logger = logging.getLogger(__name__)


# -------------------------- 3. 核心功能函数 --------------------------
def create_session():
    """创建HTTP会话（保持Cookie）"""
    session = requests.Session()
    session.timeout = 5  # 超时时间5秒
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
        }
    )
    return session


def check_login_status(session):
    """检测登录状态：返回True（已登录）/False（未登录）"""
    try:
        response = session.get(DETECT_URL)
        response.encoding = "utf-8"
        html = response.text

        if NOT_LOGGED_FLAG in html:
            logger.info("当前状态：未登录")
            return False
        elif LOGGED_SUCCESS_FLAG in html:
            logger.info("当前状态：已登录")
            return True
        else:
            logger.warning(f"状态检测异常，响应片段：{html[:100]}")
            return False

    except ConnectionError:
        logger.error("状态检测失败：无法连接服务器（可能断网）")
        return False
    except Timeout:
        logger.error("状态检测失败：请求超时")
        return False
    except RequestException as e:
        logger.error(f"状态检测异常：{str(e)}")
        return False


def login(session):
    """执行登录：返回登录结果"""
    try:
        encoded_username = quote(USERNAME)
        login_url = (
            f"{LOGIN_BASE_URL}?user_account={encoded_username}&user_password={PASSWORD}"
        )

        logger.info(f"使用url: {login_url}")
        response = session.get(login_url)
        response.encoding = "utf-8"
        result = response.text

        if LOGIN_SUCCESS_FLAG in result:
            logger.info(f"登录成功！账号：{USERNAME[:6]}****")
            return True
        elif "密码错误" in result or "账号错误" in result:
            logger.error(f"登录失败：账号或密码错误（账号：{USERNAME[:6]}****）")
            return False
        else:
            logger.error(f"登录异常，响应片段：{result[:100]}")
            return False

    except ConnectionError:
        logger.error("登录失败：无法连接登录接口")
        return False
    except Timeout:
        logger.error("登录失败：请求超时")
        return False
    except RequestException as e:
        logger.error(f"登录异常：{str(e)}")
        return False


# -------------------------- 4. 主循环 --------------------------
def main_loop():
    """主循环，在独立线程中运行"""
    global is_running, USERNAME, PASSWORD, CHECK_INTERVAL, DETECT_URL, LOGIN_BASE_URL, last_config_mtime
    global NOT_LOGGED_FLAG, LOGGED_SUCCESS_FLAG, LOGIN_SUCCESS_FLAG

    logger.info("=" * 50)
    logger.info("校园网自动登录程序启动")
    logger.info(f"检测间隔：{CHECK_INTERVAL}秒 | 账号：{USERNAME[:6]}****")
    logger.info("=" * 50)

    session = create_session()
    session_last_used = time.time()

    while is_running:
        # 每30分钟重建一次会话，避免长期连接失效
        if time.time() - session_last_used > 1800:
            session = create_session()
            session_last_used = time.time()
            logger.info("会话已重置，避免连接失效")
        # 仅当配置文件被修改时才重新加载
        try:
            current_mtime = os.path.getmtime(config_path)
            if current_mtime != last_config_mtime:
                load_config()
                # 更新配置变量
                USERNAME = config["CAMPUS_NET"]["USERNAME"]
                PASSWORD = config["CAMPUS_NET"]["PASSWORD"]
                CHECK_INTERVAL = int(config["CAMPUS_NET"]["CHECK_INTERVAL"])
                DETECT_URL = config["CAMPUS_NET"]["DETECT_URL"]
                LOGIN_BASE_URL = config["CAMPUS_NET"]["LOGIN_BASE_URL"]
                NOT_LOGGED_FLAG = config["DETECT_FLAG"]["NOT_LOGGED"]
                LOGGED_SUCCESS_FLAG = config["DETECT_FLAG"]["LOGGED_SUCCESS"]
                LOGIN_SUCCESS_FLAG = config["DETECT_FLAG"]["LOGIN_SUCCESS"]
                last_config_mtime = current_mtime
                logger.info("配置文件已更新，重新加载")
        except Exception as e:
            logger.warning(f"检查配置文件修改时间失败: {str(e)}")

        if not check_login_status(session):
            logger.info("开始自动登录...")
            login(session)
        time.sleep(CHECK_INTERVAL)

        session_last_used = time.time()  # 更新最后使用时间


# -------------------------- 5. Web接口 --------------------------
@app.route("/")
def index():
    """前端页面"""
    return render_template("index.html")


@app.route("/get_config")
def get_config():
    """获取当前配置"""
    load_config()
    return jsonify(
        {
            "username": config["CAMPUS_NET"]["USERNAME"],
            "password": config["CAMPUS_NET"]["PASSWORD"],
            "check_interval": config["CAMPUS_NET"]["CHECK_INTERVAL"],
            "detect_url": config["CAMPUS_NET"]["DETECT_URL"],
            "login_base_url": config["CAMPUS_NET"]["LOGIN_BASE_URL"],
            "not_logged_flag": config["DETECT_FLAG"]["NOT_LOGGED"],
            "logged_success_flag": config["DETECT_FLAG"]["LOGGED_SUCCESS"],
            "login_success_flag": config["DETECT_FLAG"]["LOGIN_SUCCESS"],
        }
    )


@app.route("/save_config", methods=["POST"])
def save_config():
    """保存配置"""
    try:
        data = request.json

        # 更新配置
        config["CAMPUS_NET"]["USERNAME"] = data["username"]
        config["CAMPUS_NET"]["PASSWORD"] = data["password"]
        config["CAMPUS_NET"]["CHECK_INTERVAL"] = data["check_interval"]
        config["CAMPUS_NET"]["DETECT_URL"] = data["detect_url"]
        config["CAMPUS_NET"]["LOGIN_BASE_URL"] = data["login_base_url"]
        config["DETECT_FLAG"]["NOT_LOGGED"] = data["not_logged_flag"]
        config["DETECT_FLAG"]["LOGGED_SUCCESS"] = data["logged_success_flag"]
        config["DETECT_FLAG"]["LOGIN_SUCCESS"] = data["login_success_flag"]

        # 保存到文件
        with open(config_path, "w", encoding="utf-8") as f:
            config.write(f)

        logger.info("配置已更新")
        return jsonify({"status": "success", "message": "配置保存成功"})
    except Exception as e:
        logger.error(f"保存配置失败: {str(e)}")
        return jsonify({"status": "error", "message": f"保存失败: {str(e)}"})


@app.route("/get_logs")
def get_logs():
    """获取日志内容"""
    log_buffer.seek(0)
    logs = log_buffer.read()
    return jsonify({"logs": logs})


@app.route("/get_status")
def get_status():
    """获取程序状态"""
    session = create_session()
    status = check_login_status(session)
    return jsonify(
        {
            "running": is_running,
            "login_status": status,
            "check_interval": CHECK_INTERVAL,
            "username": USERNAME[:6] + "****",
        }
    )


# -------------------------- 6. 系统托盘功能 --------------------------
def show_web_interface():
    """打开浏览器显示Web界面"""
    import webbrowser

    webbrowser.open("http://127.0.0.1:5000")


def stop_program(icon, item):
    """停止程序并退出"""
    global is_running
    is_running = False  # 终止主循环
    flask_stop_event.set()  # 触发Flask停止
    icon.stop()  # 停止托盘图标
    logger.info("程序已退出")


def create_tray_icon():
    """创建系统托盘图标和菜单"""
    # 加载图标（需准备一个.ico格式图标，放在static目录下）
    icon_path = os.path.join(base_path, "static", "icon.ico")
    try:
        image = Image.open(icon_path)
    except:
        # 若图标不存在，使用默认占位图标
        image = Image.new("RGB", (64, 64), color="blue")

    # 定义托盘菜单
    menu = (item("显示界面", show_web_interface), item("退出程序", stop_program))

    # 创建托盘图标
    icon = Icon("校园网自动登录", image, "校园网自动登录", menu)
    return icon


# -------------------------- 7. Flask服务线程 --------------------------
def run_flask():
    """在线程中启动Flask服务"""
    from werkzeug.serving import make_server

    class FlaskServer:
        def __init__(self, app):
            self.server = make_server("0.0.0.0", 5000, app)
            self.ctx = app.app_context()
            self.ctx.push()

        def run(self):
            self.server.serve_forever()

        def shutdown(self):
            self.server.shutdown()

    server = FlaskServer(app)
    # 启动服务
    flask_thread = Thread(target=server.run, daemon=True)
    flask_thread.start()
    # 等待停止信号
    flask_stop_event.wait()
    # 关闭服务
    server.shutdown()
    flask_thread.join()


# -------------------------- 8. 启动程序 --------------------------
if __name__ == "__main__":
    try:
        # 启动主循环线程
        main_thread = Thread(target=main_loop, daemon=True)
        main_thread.start()

        # 启动Flask服务线程
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()

        # 启动系统托盘
        logger.info("程序已最小化到系统托盘，右键图标可操作")
        tray_icon = create_tray_icon()
        tray_icon.run()

        # 等待所有线程结束
        main_thread.join()
        flask_thread.join()

    except Exception as e:
        # 记录顶层异常并保持窗口打开
        logger.critical(f"程序启动失败：{str(e)}", exc_info=True)

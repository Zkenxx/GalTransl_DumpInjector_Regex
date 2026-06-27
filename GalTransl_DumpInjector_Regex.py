"""
Galgame/视觉小说 文本正则提取与注入工具 (CLI Regex Mode) - Lightweight Edition
参考原版精简的轻量化版本，保留了核心的正则表达式提取与注入逻辑。
"""
import json
import logging
import re
import shutil
import argparse
from configparser import ConfigParser
from pathlib import Path

# ==============================================================================
# 全局日志配置
# ==============================================================================
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ==============================================================================
# 1. 核心业务引擎模块：文本提取
# ==============================================================================
def extract(script_jp: Path, json_jp: Path, regex: str, name_regex: str, enc: str) -> None:
    """文本提取核心工作流"""
    json_jp.mkdir(parents=True, exist_ok=True)
    msg_pat = re.compile(regex)
    name_pat = re.compile(name_regex) if name_regex else None

    for path in script_jp.glob("*"):
        if not path.is_file(): continue
        try:
            text = path.read_text(encoding=enc)
        except UnicodeDecodeError:
            # 日文脚本编码解码错误，跳过提取
            logger.error(f"解码错误跳过: {path.name}")
            continue

        results, last_end = [], 0
        for m in msg_pat.finditer(text):
            item = {}
            # 严格控制字典初始化顺序，确保 name 始终在 message 前方
            if name_pat and (name_m := name_pat.search(text, last_end, m.start(1))):
                item["name"] = name_m.group(1)
            item["message"] = m.group(1)
            results.append(item)
            last_end = m.end(1)
            
        (json_jp / f"{path.stem}.json").write_text(json.dumps(results, ensure_ascii=False, indent=4), encoding="utf-8")
    logger.info("========== 提取工作流完毕 ==========")

# ==============================================================================
# 2. 核心业务引擎模块：文本注入与字库兼容处理
# ==============================================================================
def insert(script_jp: Path, json_jp: Path, json_cn: Path, script_cn: Path, 
           jp_enc: str, cn_enc: str, regex: str, name_regex: str, sjis_char: str) -> None:
    """文本注入核心工作流"""
    script_cn.mkdir(parents=True, exist_ok=True)
    msg_pat, name_pat = re.compile(regex), re.compile(name_regex) if name_regex else None

    # 构建 SJIS 替换映射表 (利用 unicode 编码映射，提速极高)
    # 负责处理老旧引擎的 Shift-JIS 汉字字库不兼容问题（汉字映射与安全替换）
    sjis_map = {}
    if sjis_char is not None and Path("hanzi2kanji_table.txt").is_file():
        for line in Path("hanzi2kanji_table.txt").read_text(encoding="utf-8").splitlines():
            if "\t" in line:
                k, v = line.split("\t", 1)
                if not sjis_char or k in sjis_char: sjis_map[ord(k)] = v

    for path in script_jp.glob("*"):
        if not path.is_file(): continue
        jp_json, cn_json, out_path = json_jp / f"{path.stem}.json", json_cn / f"{path.stem}.json", script_cn / path.name
        
        if not jp_json.exists() or not cn_json.exists():
            # 缺失对应的 JSON 文件，直接复制原版脚本
            logger.warning(f"缺失 JSON 映射，直接复制: {path.name}")
            shutil.copy2(path, out_path)
            continue

        jp_data = json.loads(jp_json.read_text(encoding="utf-8"))
        cn_data = json.loads(cn_json.read_text(encoding="utf-8"))
        
        # 负责管理原文与译文的字典映射
        msg_dict, name_dict = {}, {}
        for jp, cn in zip(jp_data, cn_data):
            # 内存中直接完成 SJIS 替换，避免生成大量临时文件
            msg_dict[jp["message"]] = cn["message"].translate(sjis_map) if sjis_map else cn["message"]
            if "name" in jp and "name" in cn:
                name_dict[jp["name"]] = cn["name"].translate(sjis_map) if sjis_map else cn["name"]

        text = path.read_text(encoding=jp_enc, errors="ignore")
        
        # 闭包回调函数，取代原先的 TranslationMapper 类 (提供 re.sub 的正则替换回调方法)
        text = msg_pat.sub(lambda m: m.group().replace(m.group(1), msg_dict.get(m.group(1), m.group(1))), text)
        if name_pat:
            text = name_pat.sub(lambda m: m.group().replace(m.group(1), name_dict.get(m.group(1), m.group(1))), text)

        out_path.write_text(text, encoding=cn_enc, errors="ignore")
    logger.info("========== 注入工作流完毕 ==========")

# ==============================================================================
# 3. 配置与命令行生命周期模块
# ==============================================================================
def main():
    """命令行生命周期主入口，管理配置文件的读取、CLI 参数解析以及程序的入口调度。"""
    defaults = {
        "script_jp_folder": "", "json_jp_folder": "", "json_cn_folder": "", "script_cn_folder": "",
        "regex": r"", "name_regex": r"", "japanese_encoding": "shift-jis", "chinese_encoding": "gbk"
    }
    
    # 从 INI 文件加载配置覆盖硬编码缺省值
    cfg_path = Path("config.ini")
    if cfg_path.exists():
        cp = ConfigParser()
        cp.read(cfg_path, encoding="gbk")
        if "DEFAULT" in cp: defaults.update(cp["DEFAULT"])

    # 解析命令行参数
    parser = argparse.ArgumentParser(description="Galgame 正则模式提取与注入工具 (Lightweight)")
    parser.add_argument("action", choices=["extract", "insert"], help="选择操作: extract (提取) 或 insert (注入)")
    for k, v in defaults.items():
        parser.add_argument(f"--{k}", default=v)
    parser.add_argument("--sjis_replace_mode", action="store_true", help="是否启用 SJIS 字库兼容替换模式")
    parser.add_argument("--sjis_replace_char", default="", help="要替换的特定字符集合(留空为全量替换)")
    
    args = parser.parse_args()
    
    if args.action == "extract":
        extract(Path(args.script_jp_folder), Path(args.json_jp_folder), args.regex, args.name_regex, args.japanese_encoding)
    else:
        insert(Path(args.script_jp_folder), Path(args.json_jp_folder), Path(args.json_cn_folder), 
               Path(args.script_cn_folder), args.japanese_encoding, args.chinese_encoding, 
               args.regex, args.name_regex, args.sjis_replace_char if args.sjis_replace_mode else None)

# ==============================================================================
# 程序启动点
# ==============================================================================
if __name__ == "__main__":
    main()
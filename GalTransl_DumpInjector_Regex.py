"""
Galgame/视觉小说 文本正则提取与注入工具 (CLI Regex Mode)
Version: 1.3.1 (Normalized & Modularized)
Original Author: cx2333
CLI Refactor & Maintainer: Zkenxx
"""

import json
import logging
import re
import shutil
import argparse
import configparser
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Match

VERSION = "1.3.1"

# ==============================================================================
# 全局日志配置
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


# ==============================================================================
# 1. 文本映射与回调模块
# ==============================================================================
class TranslationMapper:
    """负责管理原文与译文的字典映射，并提供正则替换的回调方法。"""
    
    def __init__(self) -> None:
        self.message_dict: Dict[str, str] = {}
        self.name_dict: Dict[str, str] = {}

    def reset(self) -> None:
        """清空当前的映射字典，准备下一次注入。"""
        self.message_dict.clear()
        self.name_dict.clear()

    def get_cn_message_callback(self, matched: Match[str]) -> str:
        """
        re.sub 的正文替换回调函数。
        """
        target_text = matched.group(1)
        if target_text in self.message_dict:
            return matched.group().replace(target_text, self.message_dict[target_text])
        return matched.group()

    def get_cn_name_callback(self, matched: Match[str]) -> str:
        """
        re.sub 的人名替换回调函数。
        """
        target_text = matched.group(1)
        if target_text in self.name_dict:
            return matched.group().replace(target_text, self.name_dict[target_text])
        return matched.group()


# ==============================================================================
# 2. 字库兼容编码模块
# ==============================================================================
class SjisProxyEncoder:
    """负责处理老旧引擎的 Shift-JIS 汉字字库不兼容问题（汉字映射与安全替换）。"""

    @staticmethod
    def read_proxy_dict(filename: str, proxy_words: str = "") -> Dict[str, str]:
        """读取汉字到日文汉字（Kanji）的映射表。"""
        char_dict: Dict[str, str] = {}
        file_path = Path(filename)
        
        if not file_path.is_file():
            logger.warning(f"映射表文件 [{filename}] 不存在，将跳过字库字符替换。")
            return char_dict

        with file_path.open("r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str or "\t" not in line_str:
                    continue
                orig_char, replace_char = line_str.split("\t", 1)
                
                if proxy_words:
                    if orig_char in proxy_words:
                        char_dict[orig_char] = replace_char
                else:
                    char_dict[orig_char] = replace_char
                    
        return char_dict

    @classmethod
    def process_sjis_replace(cls, json_cn_folder: Path, replace_str: str) -> Tuple[Path, List[str], List[str]]:
        """执行 SJIS 替换模式，生成替换后的临时译文 JSON 目录。"""
        char_dict = cls.read_proxy_dict("hanzi2kanji_table.txt", replace_str)
        hanzi_chars_list: List[str] = []
        kanji_chars_list: List[str] = []
        
        replaced_folder = json_cn_folder.with_name(f"{json_cn_folder.name}_replaced")
        replaced_folder.mkdir(parents=True, exist_ok=True)
            
        for file_path in json_cn_folder.glob("*.json"):
            with file_path.open("r", encoding="utf-8") as f_in:
                input_str = f_in.read()

            output_str = ""
            for char in input_str:
                if char in char_dict:
                    output_str += char_dict[char]
                    if char not in hanzi_chars_list:
                        hanzi_chars_list.append(char)
                        kanji_chars_list.append(char_dict[char])
                else:
                    output_str += char

            replaced_file_path = replaced_folder / file_path.name
            with replaced_file_path.open("w", encoding="utf-8") as f_out:
                f_out.write(output_str)
                
        return replaced_folder, hanzi_chars_list, kanji_chars_list


# ==============================================================================
# 3. 核心业务引擎模块
# ==============================================================================
class GalTranslEngine:
    """封装提取与注入的核心业务逻辑流。"""

    def __init__(self) -> None:
        self.mapper = TranslationMapper()

    def extract_workflow(self, script_jp_folder: Path, json_jp_folder: Path, 
                         regex: str, name_regex: Optional[str], japanese_encoding: str) -> bool:
        """文本提取核心工作流。"""
        if not script_jp_folder or not json_jp_folder:
            logger.error("请提供有效的日文脚本目录和日文JSON保存目录。")
            return False
        if not regex:
            logger.error("正文提取正则不能为空。")
            return False

        message_pattern = re.compile(regex)
        name_pattern = re.compile(name_regex) if name_regex else None

        json_jp_folder.mkdir(parents=True, exist_ok=True)

        for script_path in script_jp_folder.iterdir():
            if not script_path.is_file():
                continue
                
            logger.info(f"正在提取: {script_path.name}")
            message_list: List[Dict[str, str]] = []
            
            try:
                with script_path.open("r", encoding=japanese_encoding) as f:
                    text = f.read()
            except UnicodeDecodeError:
                logger.error(f"日文脚本 [{script_path.name}] 编码解码错误，请检查编码格式。")
                return False

            search_result = message_pattern.search(text)
            last_start = 0
            
            while search_result:
                try:
                    message = search_result.group(1)
                except IndexError:
                    logger.error("正文提取正则表达式未包含有效的捕获组(Group 1)。")
                    return False
                    
                start = search_result.start(1)
                name = ""
                
                if name_regex and name_pattern:
                    name_search_result = name_pattern.search(text, last_start, start)
                    if name_search_result:
                        try:
                            name = name_search_result.group(1)
                        except IndexError:
                            logger.error("人名提取正则表达式未包含有效的捕获组(Group 1)。")
                            return False

                # 【修复】严格控制字典初始化顺序，确保 name 始终在 message 前方
                tmp_obj: Dict[str, str] = {}
                if name:
                    tmp_obj["name"] = name
                tmp_obj["message"] = message
                
                message_list.append(tmp_obj)
                
                last_start = search_result.end(1)
                search_result = message_pattern.search(text, last_start)

            out_json_path = json_jp_folder / f"{script_path.stem}.json"
            with out_json_path.open("w", encoding="utf-8") as f:
                json.dump(message_list, f, ensure_ascii=False, indent=4)
                
        logger.info("========== 提取工作流完毕 ==========")
        return True

    def insert_workflow(self, script_jp_folder: Path, json_jp_folder: Path, json_cn_folder: Path, 
                        script_cn_folder: Path, jp_encoding: str, cn_encoding: str, 
                        message_regex: str, name_regex: str, 
                        sjis_replace_mode: bool, sjis_replace_char: str) -> bool:
        """文本注入核心工作流。"""
        if not all([script_jp_folder, json_jp_folder, json_cn_folder, script_cn_folder]):
            logger.error("参数不完整，请确保提供所有必要的输入/输出目录路径。")
            return False
        if not message_regex:
            logger.error("正文提取正则不能为空。")
            return False

        script_cn_folder.mkdir(parents=True, exist_ok=True)
        self.mapper.reset()
        
        kanji_chars_list: List[str] = []
        hanzi_chars_list: List[str] = []
        
        if sjis_replace_mode:
            json_cn_folder, hanzi_chars_list, kanji_chars_list = SjisProxyEncoder.process_sjis_replace(
                json_cn_folder, sjis_replace_char
            )
            logger.info("SJIS替换模式配置信息:")
            logger.info(f'"source_characters": "{"".join(kanji_chars_list)}"')
            logger.info(f'"target_characters": "{"".join(hanzi_chars_list)}"')

        for script_path in script_jp_folder.iterdir():
            if not script_path.is_file():
                continue
                
            logger.info(f"正在注入: {script_path.name}")
            jp_json_path = json_jp_folder / f"{script_path.stem}.json"
            cn_json_path = json_cn_folder / f"{script_path.stem}.json"
            output_path = script_cn_folder / script_path.name
            
            if not jp_json_path.exists() or not cn_json_path.exists():
                logger.warning(f"缺失对应的 JSON 文件，直接复制原版脚本: {script_path.name}")
                shutil.copy2(script_path, output_path)
                continue
                
            with jp_json_path.open("r", encoding="utf-8") as f:
                jp_data = json.load(f)
            with cn_json_path.open("r", encoding="utf-8") as f:
                cn_data = json.load(f)

            for i in range(min(len(jp_data), len(cn_data))):
                self.mapper.message_dict[jp_data[i]["message"]] = cn_data[i]["message"]
                if name_regex and "name" in jp_data[i] and "name" in cn_data[i]:
                    if jp_data[i]["name"] not in self.mapper.name_dict:
                        self.mapper.name_dict[jp_data[i]["name"]] = cn_data[i]["name"]

            with script_path.open("r", encoding=jp_encoding, errors="ignore") as f:
                script_content = f.read()

            script_content = re.sub(message_regex, self.mapper.get_cn_message_callback, script_content)
            if name_regex:
                script_content = re.sub(name_regex, self.mapper.get_cn_name_callback, script_content)

            with output_path.open("w", encoding=cn_encoding, errors="ignore") as f:
                f.write(script_content)

        if sjis_replace_mode:
            logger.info("SJIS替换模式配置信息总结:")
            logger.info(f'"source_characters": "{"".join(kanji_chars_list)}"')
            logger.info(f'"target_characters": "{"".join(hanzi_chars_list)}"')
            
        logger.info("========== 注入工作流完毕 ==========")
        return True


# ==============================================================================
# 4. 配置与命令行生命周期模块
# ==============================================================================
class CLIApplication:
    """管理配置文件的读取、CLI 参数解析以及程序的入口调度。"""

    def __init__(self) -> None:
        self.engine = GalTranslEngine()
        self.defaults: Dict[str, str] = {
            "script_jp_folder": "",
            "json_jp_folder": "",
            "json_cn_folder": "",
            "script_cn_folder": "",
            "regex": r"",
            "name_regex": r"",
            "japanese_encoding": "shift-jis",
            "chinese_encoding": "gbk",
        }

    def load_ini_config(self, config_path: str = "config.ini") -> None:
        """从 INI 文件加载配置覆盖硬编码缺省值。"""
        path = Path(config_path)
        if path.exists():
            config = configparser.ConfigParser()
            config.read(path, encoding="gbk")
            if "DEFAULT" in config:
                for key in self.defaults.keys():
                    if key in config["DEFAULT"]:
                        self.defaults[key] = config["DEFAULT"][key]

    def parse_arguments(self) -> argparse.Namespace:
        """解析命令行参数。"""
        parser = argparse.ArgumentParser(
            description="Galgame 正则表达式模式文本提取与注入工具",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )
        parser.add_argument("action", choices=["extract", "insert"], help="选择操作: extract (提取) 或 insert (注入)")
        
        parser.add_argument("--script_jp_folder", default=self.defaults["script_jp_folder"], help="日文脚本文件夹")
        parser.add_argument("--json_jp_folder", default=self.defaults["json_jp_folder"], help="日文JSON保存文件夹")
        parser.add_argument("--json_cn_folder", default=self.defaults["json_cn_folder"], help="译文JSON文件夹")
        parser.add_argument("--script_cn_folder", default=self.defaults["script_cn_folder"], help="译文脚本保存文件夹")
        
        parser.add_argument("--regex", default=self.defaults["regex"], help="正文提取正则")
        parser.add_argument("--name_regex", default=self.defaults["name_regex"], help="人名提取正则")
        
        parser.add_argument("--jp_encoding", default=self.defaults["japanese_encoding"], help="日文源文件编码")
        parser.add_argument("--cn_encoding", default=self.defaults["chinese_encoding"], help="中文目标文件编码")
        
        parser.add_argument("--sjis_replace_mode", action="store_true", help="是否启用 SJIS 字库兼容替换模式")
        parser.add_argument("--sjis_replace_char", default="", help="要替换的特定字符集合(留空为全量替换)")

        return parser.parse_args()

    def run(self) -> None:
        """命令行生命周期主入口。"""
        logger.info(f"GalTransl 正则提取注入工具 {VERSION} (Refactored by zkenxx)")
        self.load_ini_config()
        args = self.parse_arguments()

        if args.action == "extract":
            self.engine.extract_workflow(
                script_jp_folder=Path(args.script_jp_folder),
                json_jp_folder=Path(args.json_jp_folder),
                regex=args.regex,
                name_regex=args.name_regex,
                japanese_encoding=args.jp_encoding
            )
        elif args.action == "insert":
            self.engine.insert_workflow(
                script_jp_folder=Path(args.script_jp_folder),
                json_jp_folder=Path(args.json_jp_folder),
                json_cn_folder=Path(args.json_cn_folder),
                script_cn_folder=Path(args.script_cn_folder),
                jp_encoding=args.jp_encoding,
                cn_encoding=args.cn_encoding,
                message_regex=args.regex,
                name_regex=args.name_regex,
                sjis_replace_mode=args.sjis_replace_mode,
                sjis_replace_char=args.sjis_replace_char
            )


# ==============================================================================
# 程序启动点
# ==============================================================================
if __name__ == "__main__":
    app = CLIApplication()
    app.run()
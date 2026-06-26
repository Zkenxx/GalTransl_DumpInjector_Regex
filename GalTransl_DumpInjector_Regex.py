import json
import os
import re
import shutil
import argparse
import configparser
from typing import Dict, List, Tuple, Optional

VERSION = "1.2 (CLI Modular Single-File Mode)"


# ==============================================================================
# 1. 文本映射与回调模块 (Translation Mapper)
# ==============================================================================
class TranslationMapper:
    """负责管理原文与译文的字典映射，并提供正则替换的回调方法"""
    
    def __init__(self):
        self.message_dict: Dict[str, str] = {}
        self.name_dict: Dict[str, str] = {}

    def reset(self):
        """清空映射字典"""
        self.message_dict.clear()
        self.name_dict.clear()

    def get_cn_message_callback(self, matched: re.Match) -> str:
        """re.sub 的正文替换回调函数"""
        target_text = matched.group(1)
        if target_text in self.message_dict:
            return matched.group().replace(target_text, self.message_dict[target_text])
        return matched.group()

    def get_cn_name_callback(self, matched: re.Match) -> str:
        """re.sub 的人名替换回调函数"""
        target_text = matched.group(1)
        if target_text in self.name_dict:
            return matched.group().replace(target_text, self.name_dict[target_text])
        return matched.group()


# ==============================================================================
# 2. 字库兼容编码模块 (SJIS Proxy Encoder)
# ==============================================================================
class SjisProxyEncoder:
    """负责处理老旧引擎的 Shift-JIS 汉字字库不兼容问题（汉字映射/安全替换）"""

    @staticmethod
    def read_proxy_dict(filename: str, proxy_words: str = "") -> Dict[str, str]:
        """读取汉字到日文汉字（Kanji）的映射表"""
        char_dict = {}
        if not os.path.exists(filename):
            print(f"警告: 映射表文件 [{filename}] 不存在，跳过字符替换。")
            return char_dict

        with open(filename, "r", encoding="utf-8") as f:
            for line in f.readlines():
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
    def process_sjis_replace(cls, json_cn_folder: str, replace_str: str) -> Tuple[str, List[str], List[str]]:
        """执行 SJIS 替换模式，生成替换后的临时译文 JSON 目录"""
        char_dict = cls.read_proxy_dict("hanzi2kanji_table.txt", replace_str)
        hanzi_chars_list: List[str] = []
        kanji_chars_list: List[str] = []
        
        trans_json_replaced_folder = json_cn_folder + "_replaced"
        if not os.path.exists(trans_json_replaced_folder):
            os.mkdir(trans_json_replaced_folder)
            
        for file_name in os.listdir(json_cn_folder):
            if not file_name.endswith(".json"):
                continue
            file_path = os.path.join(json_cn_folder, file_name)
            replaced_file_path = os.path.join(trans_json_replaced_folder, file_name)
            
            with open(file_path, "r", encoding="utf-8") as f_in:
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

            with open(replaced_file_path, "w", encoding="utf-8") as f_out:
                f_out.write(output_str)
                
        return trans_json_replaced_folder, hanzi_chars_list, kanji_chars_list


# ==============================================================================
# 3. 核心业务引擎模块 (GalTransl Engine)
# ==============================================================================
class GalTranslEngine:
    """封装提取与注入的核心业务逻辑"""

    def __init__(self):
        self.mapper = TranslationMapper()

    def extract_workflow(self, script_jp_folder: str, json_jp_folder: str, 
                         regex: str, name_regex: Optional[str], japanese_encoding: str) -> bool:
        """文本提取核心流"""
        if not script_jp_folder or not json_jp_folder:
            print("错误: 请提供日文脚本目录和日文JSON保存目录.")
            return False
        if not regex:
            print("错误: 正文提取正则不能为空.")
            return False

        message_pattern = re.compile(regex)
        name_pattern = re.compile(name_regex) if name_regex else None

        if not os.path.exists(json_jp_folder):
            os.makedirs(json_jp_folder)

        for filename in os.listdir(script_jp_folder):
            print(f"正在提取: {filename}")
            message_list = []
            script_path = os.path.join(script_jp_folder, filename)
            
            try:
                with open(script_path, "r", encoding=japanese_encoding) as f:
                    text = f.read()
            except UnicodeDecodeError:
                print(f"错误: 日文脚本 [{filename}] 编码解码错误")
                return False

            search_result = message_pattern.search(text)
            last_start = 0
            while search_result:
                try:
                    message = search_result.group(1)
                except IndexError:
                    print("错误: 正文提取正则表达式未包含括号(Group 1)")
                    return False
                    
                start = search_result.start(1)
                name = ""
                if name_regex and name_pattern:
                    name_search_result = name_pattern.search(text, last_start, start)
                    if name_search_result:
                        try:
                            name = name_search_result.group(1)
                        except IndexError:
                            print("错误: 人名提取正则表达式未包含括号(Group 1)")
                            return False

                tmp_obj = {"name": name, "message": message}
                if name == "":
                    del tmp_obj["name"]
                message_list.append(tmp_obj)
                
                last_start = search_result.end(1)
                search_result = message_pattern.search(text, last_start)

            out_json_path = os.path.join(json_jp_folder, os.path.splitext(filename)[0] + ".json")
            with open(out_json_path, "w", encoding="utf-8") as f:
                json.dump(message_list, f, ensure_ascii=False, indent=4)
                
        print("----- 提取完毕 -----")
        return True

    def insert_workflow(self, script_jp_folder: str, json_jp_folder: str, json_cn_folder: str, 
                         script_cn_folder: str, jp_encoding: str, cn_encoding: str, 
                         message_regex: str, name_regex: str, 
                         sjis_replace_mode: bool, sjis_replace_char: str) -> bool:
        """文本注入核心流"""
        if not script_jp_folder or not json_jp_folder or not json_cn_folder or not script_cn_folder:
            print("错误: 请确保提供日文脚本目录、日文JSON目录、译文JSON目录和译文脚本保存目录.")
            return False
        if not message_regex:
            print("错误: 正文提取正则不能为空.")
            return False

        if not os.path.exists(script_cn_folder):
            os.makedirs(script_cn_folder)

        self.mapper.reset()
        hanzi_chars_list: List[str] = []
        kanji_chars_list: List[str] = []
        
        # 预处理：字库安全替换模式
        if sjis_replace_mode:
            json_cn_folder, hanzi_chars_list, kanji_chars_list = SjisProxyEncoder.process_sjis_replace(
                json_cn_folder, sjis_replace_char
            )
            print("sjis替换模式配置:\n")
            print(f'"source_characters":"{"".join(kanji_chars_list)}",\n')
            print(f'"target_characters":"{"".join(hanzi_chars_list)}"\n')

        # 遍历注入
        for filename in os.listdir(script_jp_folder):
            print(f"正在注入: {filename}")
            script_path = os.path.join(script_jp_folder, filename)
            jp_json_path = os.path.join(json_jp_folder, os.path.splitext(filename)[0] + ".json")
            cn_json_path = os.path.join(json_cn_folder, os.path.splitext(filename)[0] + ".json")
            
            # 严格保留原版逻辑：JSON不存在则直接复制原文文件
            if not os.path.exists(jp_json_path) or not os.path.exists(cn_json_path):
                shutil.copy(script_path, script_cn_folder)
                continue
                
            with open(jp_json_path, "r", encoding="utf-8") as f:
                jp_data = json.load(f)
            with open(cn_json_path, "r", encoding="utf-8") as f:
                cn_data = json.load(f)

            # 累加映射字典
            for i in range(min(len(jp_data), len(cn_data))):
                self.mapper.message_dict[jp_data[i]["message"]] = cn_data[i]["message"]
                if name_regex != "":
                    if "name" in jp_data[i] and "name" in cn_data[i]:
                        if jp_data[i]["name"] not in self.mapper.name_dict:
                            self.mapper.name_dict[jp_data[i]["name"]] = cn_data[i]["name"]

            with open(script_path, "r", encoding=jp_encoding, errors="ignore") as f:
                script_content = f.read()

            # 执行注入替换
            script_content = re.sub(message_regex, self.mapper.get_cn_message_callback, script_content)
            if name_regex != "":
                script_content = re.sub(name_regex, self.mapper.get_cn_name_callback, script_content)

            output_path = os.path.join(script_cn_folder, filename)
            with open(output_path, "w", encoding=cn_encoding, errors="ignore") as f:
                f.write(script_content)

        if sjis_replace_mode:
            print("sjis替换模式配置:\n")
            print(f'"source_characters":"{"".join(kanji_chars_list)}",\n')
            print(f'"target_characters":"{"".join(hanzi_chars_list)}"\n')
            
        print("----- 注入完毕 -----")
        return True


# ==============================================================================
# 4. 配置与命令行生命周期模块 (CLI Application)
# ==============================================================================
class CLIApplication:
    """管理配置文件的读取、CLI 参数解析以及程序的入口调度"""

    def __init__(self):
        self.engine = GalTranslEngine()
        self.defaults = {
            "script_jp_folder": "",
            "json_jp_folder": "",
            "json_cn_folder": "",
            "script_cn_folder": "",
            "regex": r"",
            "name_regex": r"",
            "japanese_encoding": "shift",
            "chinese_encoding": "gbk",
        }

    def load_ini_config(self, config_path: str = "config.ini"):
        """加载 INI 配置文件覆盖硬编码缺省值"""
        if os.path.exists(config_path):
            config = configparser.ConfigParser()
            config.read(config_path)
            if "DEFAULT" in config:
                for key in self.defaults.keys():
                    if key in config["DEFAULT"]:
                        self.defaults[key] = config["DEFAULT"][key]

    def parse_arguments(self) -> argparse.Namespace:
        """解析命令行参数"""
        parser = argparse.ArgumentParser(description="正则表达式模式 文本提取与注入工具 (面向对象模块化版)")
        parser.add_argument("action", choices=["extract", "insert"], help="选择操作: extract (提取) 或 insert (注入)")
        
        # 目录路径参数
        parser.add_argument("--script_jp_folder", default=self.defaults["script_jp_folder"], help="日文脚本文件夹")
        parser.add_argument("--json_jp_folder", default=self.defaults["json_jp_folder"], help="日文JSON保存文件夹")
        parser.add_argument("--json_cn_folder", default=self.defaults["json_cn_folder"], help="译文JSON文件夹")
        parser.add_argument("--script_cn_folder", default=self.defaults["script_cn_folder"], help="译文脚本保存文件夹")
        
        # 正则参数
        parser.add_argument("--regex", default=self.defaults["regex"], help="正文提取正则")
        parser.add_argument("--name_regex", default=self.defaults["name_regex"], help="人名提取正则")
        
        # 编码/特定优化参数
        parser.add_argument("--jp_encoding", default=self.defaults["japanese_encoding"], help="日文脚本编码")
        parser.add_argument("--cn_encoding", default=self.defaults["chinese_encoding"], help="中文脚本编码")
        parser.add_argument("--sjis_replace_mode", action="store_true", help="启用 SJIS 替换模式注入")
        parser.add_argument("--sjis_replace_char", default="", help="要替换的字符(留空为全量替换)")

        return parser.parse_args()

    def run(self):
        """生命周期主入口"""
        print(f"GalTransl 正则提取注入工具 {VERSION} by zkenxx")
        self.load_ini_config()
        args = self.parse_arguments()

        if args.action == "extract":
            self.engine.extract_workflow(
                script_jp_folder=args.script_jp_folder,
                json_jp_folder=args.json_jp_folder,
                regex=args.regex,
                name_regex=args.name_regex,
                japanese_encoding=args.jp_encoding
            )
        elif args.action == "insert":
            self.engine.insert_workflow(
                script_jp_folder=args.script_jp_folder,
                json_jp_folder=args.json_jp_folder,
                json_cn_folder=args.json_cn_folder,
                script_cn_folder=args.script_cn_folder,
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
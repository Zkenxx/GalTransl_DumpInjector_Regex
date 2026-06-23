import os
import re
import json
import shutil
import logging

# 初始化日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ],
)


def load_char_replacement_table(filepath, filter_chars=""):
    """
    读取字符替换表，返回替换字典。
    :param filepath: 替换表文件路径，格式要求为：原字符\t替代字符
    :param filter_chars: 仅替换该字符串内的字符，空表示全部
    :return: 替换字典 {原字符: 替代字符}
    """
    replacement_dict = {}
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) != 2:
                    logging.warning(f"跳过格式不符合的行: {line}")
                    continue
                orig_char, replace_char = parts
                if filter_chars:
                    if orig_char in filter_chars:
                        replacement_dict[orig_char] = replace_char
                else:
                    replacement_dict[orig_char] = replace_char
    except FileNotFoundError:
        logging.error(f"替换表文件不存在: {filepath}")
        raise
    except Exception as ex:
        logging.error(f"读取替换表出错: {ex}")
        raise
    logging.info(f"读取替换表完成，替换字符数: {len(replacement_dict)}")
    return replacement_dict


def apply_char_replacement_to_json_folder(src_json_folder, filter_chars=""):
    """
    将指定json目录内所有文件内容的字符按替换表替换，生成替换后目录。
    :param src_json_folder: 源json文件夹路径
    :param filter_chars: 限制替换的原字符集合，空表示替换全部
    :return: 新目录路径, 替换的原字符列表, 替换后的字符列表
    """
    replacement_table_path = "hanzi2kanji_table.txt"
    replacement_dict = load_char_replacement_table(replacement_table_path, filter_chars)

    replaced_json_folder = f"{src_json_folder}_replaced"
    if not os.path.exists(replaced_json_folder):
        os.makedirs(replaced_json_folder)

    original_chars_used = []
    replaced_chars_used = []

    file_names = os.listdir(src_json_folder)
    for file_name in file_names:
        src_file_path = os.path.join(src_json_folder, file_name)
        dest_file_path = os.path.join(replaced_json_folder, file_name)

        if not os.path.isfile(src_file_path):
            logging.debug(f"跳过非文件: {src_file_path}")
            continue

        try:
            with open(src_file_path, "r", encoding="utf-8") as f_in:
                content = f_in.read()
        except Exception as e:
            logging.error(f"读取文件失败 {src_file_path}: {e}")
            continue

        replaced_content_chars = []
        for ch in content:
            if ch in replacement_dict:
                replaced_content_chars.append(replacement_dict[ch])
                if ch not in original_chars_used:
                    original_chars_used.append(ch)
                    replaced_chars_used.append(replacement_dict[ch])
            else:
                replaced_content_chars.append(ch)

        replaced_content = "".join(replaced_content_chars)

        try:
            with open(dest_file_path, "w", encoding="utf-8") as f_out:
                f_out.write(replaced_content)
        except Exception as e:
            logging.error(f"写入文件失败 {dest_file_path}: {e}")
            continue

    logging.info(f"完成所有文件替换，输出目录: {replaced_json_folder}")
    return replaced_json_folder, original_chars_used, replaced_chars_used


def replace_message_callback(match_obj, replacement_dict):
    """
    正文替换回调函数。
    :param match_obj: regex匹配对象
    :param replacement_dict: 替换字典，键是原文，值是译文
    :return: 替换后的字符串或原字符串
    """
    orig_text = match_obj.group(1)
    if orig_text in replacement_dict:
        return match_obj.group().replace(orig_text, replacement_dict[orig_text])
    return match_obj.group()


def replace_name_callback(match_obj, name_replacement_dict):
    """
    人名替换回调函数。
    :param match_obj: regex匹配对象
    :param name_replacement_dict: 人名替换字典
    :return: 替换后字符串或原字符串
    """
    orig_name = match_obj.group(1)
    if orig_name in name_replacement_dict:
        return match_obj.group().replace(orig_name, name_replacement_dict[orig_name])
    return match_obj.group()


def extract_texts_from_scripts(
    jp_script_folder,
    output_json_folder,
    main_regex_pattern,
    name_regex_pattern="",
    encoding="sjis",
):
    """
    根据正则表达式，从日文脚本目录提取文本信息保存成json文件。
    :param jp_script_folder: 日文脚本目录
    :param output_json_folder: json保存目录
    :param main_regex_pattern: 正文提取正则，字符串形式，必须包含捕获组
    :param name_regex_pattern: 人名提取正则，可选，字符串形式
    :param encoding: 脚本文件编码，默认sjis
    """
    if not os.path.exists(jp_script_folder):
        raise FileNotFoundError(f"日文脚本目录不存在: {jp_script_folder}")
    if not os.path.exists(output_json_folder):
        os.makedirs(output_json_folder)

    main_pattern = re.compile(main_regex_pattern)
    name_pattern = re.compile(name_regex_pattern) if name_regex_pattern else None

    for filename in os.listdir(jp_script_folder):
        file_path = os.path.join(jp_script_folder, filename)
        if not os.path.isfile(file_path):
            continue

        try:
            with open(file_path, "r", encoding=encoding) as f:
                script_text = f.read()
        except UnicodeDecodeError as e:
            logging.error(f"{filename}解码失败: {e}")
            raise
        except Exception as e:
            logging.error(f"{filename}读取失败: {e}")
            continue

        extracted_items = []
        search_pos = 0
        while True:
            match = main_pattern.search(script_text, pos=search_pos)
            if not match:
                break

            try:
                message_text = match.group(1)
            except IndexError:
                raise ValueError("正文正则表达式需包含捕获括号")

            # 名字识别：从上一次匹配结束处查找到当前正文开始处，匹配人名正则
            name_text = ""
            if name_pattern:
                name_match = name_pattern.search(script_text, search_pos, match.start(1))
                if name_match:
                    try:
                        name_text = name_match.group(1)
                    except IndexError:
                        raise ValueError("人名正则表达式需包含捕获括号")

            extracted_obj = {"message": message_text}
            if name_text:
                extracted_obj["name"] = name_text

            extracted_items.append(extracted_obj)
            search_pos = match.end(1)

        output_json_path = os.path.join(output_json_folder, os.path.splitext(filename)[0] + ".json")
        try:
            with open(output_json_path, "w", encoding="utf-8") as f_out:
                json.dump(extracted_items, f_out, ensure_ascii=False, indent=4)
            logging.info(f"成功提取并保存：{output_json_path}, 条数: {len(extracted_items)}")
        except Exception as e:
            logging.error(f"保存json出错 {output_json_path}: {e}")


def insert_translation_to_scripts(
    jp_script_folder,
    jp_json_folder,
    cn_json_folder,
    output_cn_script_folder,
    main_regex_pattern,
    name_regex_pattern="",
    jp_encoding="sjis",
    cn_encoding="gbk",
    enable_sjis_replacement=False,
    sjis_replacement_chars=""
):
    """
    将中文翻译内容注入回脚本，根据json对应替换。
    :param jp_script_folder: 原始日文脚本目录
    :param jp_json_folder: 日文提取json目录
    :param cn_json_folder: 中文翻译json目录
    :param output_cn_script_folder: 中文脚本输出目录
    :param main_regex_pattern: 正文匹配正则字符串，必须包含捕获组
    :param name_regex_pattern: 人名匹配正则字符串，可选
    :param jp_encoding: 日文脚本编码
    :param cn_encoding: 中文脚本编码
    :param enable_sjis_replacement: 是否对中文json文本做替换操作
    :param sjis_replacement_chars: 要替换的原字符集合，空表示全部替换
    :return: 如果启用替换，返回替换字符映射字典，否则返回空dict
    """
    if not os.path.exists(jp_script_folder):
        raise FileNotFoundError(f"日文脚本目录不存在: {jp_script_folder}")
    if not os.path.exists(jp_json_folder):
        raise FileNotFoundError(f"日文json目录不存在: {jp_json_folder}")
    if not os.path.exists(cn_json_folder):
        raise FileNotFoundError(f"中文译文json目录不存在: {cn_json_folder}")
    if not os.path.exists(output_cn_script_folder):
        os.makedirs(output_cn_script_folder)
    if not main_regex_pattern:
        raise ValueError("请输入有效的正则表达式")

    # 对中文json做字符替换处理，避免部分字符无法编码或显示
    if enable_sjis_replacement:
        cn_json_folder, replaced_orig_chars, replaced_target_chars = apply_char_replacement_to_json_folder(
            cn_json_folder, sjis_replacement_chars
        )
    else:
        replaced_orig_chars, replaced_target_chars = [], []

    message_replacements = {}
    name_replacements = {}
    main_pattern = re.compile(main_regex_pattern)
    name_pattern = re.compile(name_regex_pattern) if name_regex_pattern else None

    for filename in os.listdir(jp_script_folder):
        jp_script_path = os.path.join(jp_script_folder, filename)
        if not os.path.isfile(jp_script_path):
            continue

        jp_json_path = os.path.join(jp_json_folder, os.path.splitext(filename)[0] + ".json")
        cn_json_path = os.path.join(cn_json_folder, os.path.splitext(filename)[0] + ".json")

        # 缺少json则直接复制文件，跳过翻译替换
        if not os.path.exists(jp_json_path) or not os.path.exists(cn_json_path):
            shutil.copy(jp_script_path, os.path.join(output_cn_script_folder, filename))
            logging.warning(f"缺少对应json，直接复制文件: {filename}")
            continue

        try:
            with open(jp_json_path, "r", encoding="utf-8") as f_jp_json:
                jp_entries = json.load(f_jp_json)
            with open(cn_json_path, "r", encoding="utf-8") as f_cn_json:
                cn_entries = json.load(f_cn_json)
        except Exception as e:
            logging.error(f"加载json失败 {filename}: {e}")
            shutil.copy(jp_script_path, os.path.join(output_cn_script_folder, filename))
            continue

        # 校验日文与中文json条目数是否一致
        if len(jp_entries) != len(cn_entries):
            logging.error(f"文件条目数不匹配，跳过替换: {filename}，日文条目{len(jp_entries)}，中文条目{len(cn_entries)}")
            shutil.copy(jp_script_path, os.path.join(output_cn_script_folder, filename))
            continue

        # 构建正文与人名替换字典
        for i in range(len(jp_entries)):
            jp_msg = jp_entries[i].get("message", "")
            cn_msg = cn_entries[i].get("message", "")
            message_replacements[jp_msg] = cn_msg

            if name_pattern:
                jp_name = jp_entries[i].get("name", "")
                cn_name = cn_entries[i].get("name", "")
                if jp_name and cn_name and (jp_name not in name_replacements):
                    name_replacements[jp_name] = cn_name

        # 读取原始脚本
        try:
            with open(jp_script_path, "r", encoding=jp_encoding, errors="ignore") as f_script:
                script_content = f_script.read()
        except Exception as e:
            logging.error(f"读取脚本失败 {filename}: {e}")
            continue

        # 正文替换
        script_content = main_pattern.sub(lambda m: replace_message_callback(m, message_replacements), script_content)

        # 如果有名字正则，则替换人名
        if name_pattern:
            script_content = name_pattern.sub(lambda m: replace_name_callback(m, name_replacements), script_content)

        # 写入替换后的中文脚本
        out_script_path = os.path.join(output_cn_script_folder, filename)
        try:
            with open(out_script_path, "w", encoding=cn_encoding, errors="ignore") as f_out:
                f_out.write(script_content)
            logging.info(f"脚本写入成功: {out_script_path}")
        except Exception as e:
            logging.error(f"写入中文脚本失败 {filename}: {e}")

    if enable_sjis_replacement:
        return {
            "source_characters": "".join(replaced_orig_chars),
            "target_characters": "".join(replaced_target_chars),
        }
    else:
        return {}


if __name__ == "__main__":
    # 示例调用（请根据实际路径和正则替换）：

    # extract_texts_from_scripts(
    #     jp_script_folder="path/to/jp_scripts",
    #     output_json_folder="path/to/output_jp_json",
    #     main_regex_pattern=r"your_main_regex",
    #     name_regex_pattern=r"your_name_regex",
    #     encoding="sjis"
    # )

    # insert_translation_to_scripts(
    #     jp_script_folder="path/to/jp_scripts",
    #     jp_json_folder="path/to/output_jp_json",
    #     cn_json_folder="path/to/cn_json",
    #     output_cn_script_folder="path/to/output_cn_scripts",
    #     main_regex_pattern=r"your_main_regex",
    #     name_regex_pattern=r"your_name_regex",
    #     jp_encoding="sjis",
    #     cn_encoding="gbk",
    #     enable_sjis_replacement=True,
    #     sjis_replacement_chars=""
    # )

    pass

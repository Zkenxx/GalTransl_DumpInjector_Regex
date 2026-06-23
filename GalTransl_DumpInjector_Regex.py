import os
import re
import json
import shutil


def read_proxy_dict(filename, proxy_words=""):
    """
    读取字符替换表，返回字典。
    :param filename: 替换表文件路径，格式：原字符\t替代字符
    :param proxy_words: 限制替换的原字符集合（空表示全部）
    :return: 字符替换字典
    """
    char_dict = {}
    with open(filename, "r", encoding="utf-8") as f:
        for line in f.readlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            orig_char, replace_char = parts
            if proxy_words != "":
                if orig_char in proxy_words:
                    char_dict[orig_char] = replace_char
            else:
                char_dict[orig_char] = replace_char

    return char_dict


def sjis_replace(json_cn_folder, replace_str):
    """
    根据替换表对json目录内所有文件做字符替换，生成新目录并返回。
    :param json_cn_folder: 中文json文件夹路径
    :param replace_str: 替换限定字符串（要替换的原字符集合，空表示全替换）
    :return: 新生成替换后json目录路径，替换使用的原字符列表，替换后字符列表
    """
    char_dict = read_proxy_dict("hanzi2kanji_table.txt", replace_str)
    hanzi_chars_list = []
    kanji_chars_list = []
    trans_json_replacead_folder = json_cn_folder + "_replaced"

    if not os.path.exists(trans_json_replacead_folder):
        os.mkdir(trans_json_replacead_folder)
    for file_name in os.listdir(json_cn_folder):
        file_path = os.path.join(json_cn_folder, file_name)
        replaced_file_path = os.path.join(trans_json_replacead_folder, file_name)
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
    return trans_json_replacead_folder, hanzi_chars_list, kanji_chars_list


def get_cn_message(matched, message_dict):
    """
    正文替换回调函数
    """
    if matched.group(1) in message_dict:
        return matched.group().replace(matched.group(1), message_dict[matched.group(1)])
    else:
        return matched.group()


def get_cn_name(matched, name_dict):
    """
    人名替换回调函数
    """
    if matched.group(1) in name_dict:
        return matched.group().replace(matched.group(1), name_dict[matched.group(1)])
    else:
        return matched.group()


def extract_re(
    script_jp_folder,
    json_jp_folder,
    regex_pattern,
    name_regex_pattern="",
    japanese_encoding="sjis",
):
    """
    根据正则表达式从日文脚本目录提取信息保存成json文件。
    :param script_jp_folder: 日文脚本目录
    :param json_jp_folder: 日文json保存目录
    :param regex_pattern: 正文提取正则（字符串形式）
    :param name_regex_pattern: 人名提取正则（可选）
    :param japanese_encoding: 脚本编码，默认sjis
    """
    if not os.path.exists(script_jp_folder):
        raise FileNotFoundError(f"日文脚本目录不存在: {script_jp_folder}")
    if not os.path.exists(json_jp_folder):
        os.makedirs(json_jp_folder)

    message_pattern = re.compile(regex_pattern)
    name_pattern = re.compile(name_regex_pattern) if name_regex_pattern else None

    for filename in os.listdir(script_jp_folder):
        file_path = os.path.join(script_jp_folder, filename)
        if not os.path.isfile(file_path):
            continue

        message_list = []
        try:
            with open(file_path, "r", encoding=japanese_encoding) as f:
                text = f.read()
        except UnicodeDecodeError as e:
            raise UnicodeDecodeError("日文脚本编码解码错误: " + str(e))

        search_result = message_pattern.search(text)
        last_start = 0
        while search_result:
            try:
                message = search_result.group(1)
            except IndexError:
                raise ValueError("正则表达式未包含捕获括号，至少应包含一个")

            start = search_result.start(1)
            name = ""
            if name_pattern:
                name_search_result = name_pattern.search(text, last_start, start)
                if name_search_result:
                    try:
                        name = name_search_result.group(1)
                    except IndexError:
                        raise ValueError("人名正则表达式未包含捕获括号")
                else:
                    name = ""

            tmp_obj = {"message": message}
            if name != "":
                tmp_obj["name"] = name

            message_list.append(tmp_obj)
            last_start = search_result.end(1)
            search_result = message_pattern.search(text, last_start)

        json_path = os.path.join(json_jp_folder, os.path.splitext(filename)[0] + ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(message_list, f, ensure_ascii=False, indent=4)


def insert_re(
    script_jp_folder,
    json_jp_folder,
    json_cn_folder,
    script_cn_folder,
    regex_pattern,
    name_regex_pattern="",
    japanese_encoding="sjis",
    chinese_encoding="gbk",
    sjis_replace_mode=False,
    sjis_replace_chars="",
):
    """
    根据提取的json文件注入中文内容回脚本文件。
    :param script_jp_folder: 日文脚本目录
    :param json_jp_folder: 日文json目录
    :param json_cn_folder: 中文json目录
    :param script_cn_folder: 中文脚本保存目录
    :param regex_pattern: 正文提取正则（字符串）
    :param name_regex_pattern: 人名提取正则（字符串，可空）
    :param japanese_encoding: 日文脚本编码，默认sjis
    :param chinese_encoding: 中文脚本编码，默认gbk
    :param sjis_replace_mode: 是否启用sjis替换模式
    :param sjis_replace_chars: 替换字符限定字符串（空表示全部替换）
    """
    if not os.path.exists(script_jp_folder):
        raise FileNotFoundError(f"日文脚本目录不存在: {script_jp_folder}")
    if not os.path.exists(json_jp_folder):
        raise FileNotFoundError(f"日文json目录不存在: {json_jp_folder}")
    if not os.path.exists(json_cn_folder):
        raise FileNotFoundError(f"译文json目录不存在: {json_cn_folder}")
    if not os.path.exists(script_cn_folder):
        os.makedirs(script_cn_folder)
    if not regex_pattern:
        raise ValueError("请输入正则表达式")

    # 如果开启sjis替换，先做替换
    if sjis_replace_mode:
        json_cn_folder, hanzi_chars_list, kanji_chars_list = sjis_replace(
            json_cn_folder, sjis_replace_chars
        )
    else:
        hanzi_chars_list = []
        kanji_chars_list = []

    message_dict = {}
    name_dict = {}
    message_pattern = re.compile(regex_pattern)
    name_pattern = re.compile(name_regex_pattern) if name_regex_pattern else None

    for filename in os.listdir(script_jp_folder):
        file_path = os.path.join(script_jp_folder, filename)
        if not os.path.isfile(file_path):
            continue
        jp_json_path = os.path.join(json_jp_folder, os.path.splitext(filename)[0] + ".json")
        cn_json_path = os.path.join(json_cn_folder, os.path.splitext(filename)[0] + ".json")

        # 如果对应json不存在则直接复制文件到目标目录
        if not os.path.exists(jp_json_path) or not os.path.exists(cn_json_path):
            shutil.copy(file_path, os.path.join(script_cn_folder, filename))
            continue

        with open(jp_json_path, "r", encoding="utf-8") as f:
            jp_data = json.load(f)
        with open(cn_json_path, "r", encoding="utf-8") as f:
            cn_data = json.load(f)

        for i in range(len(jp_data)):
            message_dict[jp_data[i]["message"]] = cn_data[i]["message"]
            if name_pattern:
                if "name" in jp_data[i] and "name" in cn_data[i]:
                    if jp_data[i]["name"] not in name_dict:
                        name_dict[jp_data[i]["name"]] = cn_data[i]["name"]

        with open(file_path, "r", encoding=japanese_encoding, errors="ignore") as f:
            script_content = f.read()

        # 替换正文
        script_content = message_pattern.sub(
            lambda m: get_cn_message(m, message_dict), script_content
        )
        # 替换人名
        if name_pattern:
            script_content = name_pattern.sub(
                lambda m: get_cn_name(m, name_dict), script_content
            )

        output_path = os.path.join(script_cn_folder, filename)
        with open(output_path, "w", encoding=chinese_encoding, errors="ignore") as f:
            f.write(script_content)

    # 返回替换字符配置，方便打印或其他用途
    if sjis_replace_mode:
        return {
            "source_characters": "".join(kanji_chars_list),
            "target_characters": "".join(hanzi_chars_list),
        }
    else:
        return {}


if __name__ == "__main__":
    # 示例调用：
    # extract_re("path/to/jp_scripts", "path/to/output_json", r"your_regex", r"name_regex", "sjis")
    # insert_re("path/to/jp_scripts", "path/to/jp_json", "path/to/cn_json", "path/to/output_scripts",
    #           r"your_regex", r"name_regex", "sjis", "gbk", sjis_replace_mode=True, sjis_replace_chars="")

    # 请根据需要填写参数调用上面两个函数
    pass


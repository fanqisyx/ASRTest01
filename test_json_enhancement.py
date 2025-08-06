#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试JSON增强功能的脚本
"""
import json
import datetime

def test_json_enhancement():
    """测试JSON时间ID添加功能"""
    
    # 模拟AI返回的JSON响应
    original_json = {
        "command": "play_music",
        "params": {
            "song": "测试歌曲",
            "volume": 80
        }
    }
    
    # 转换为字符串（模拟从AI获取的文本）
    answer = json.dumps(original_json, ensure_ascii=False)
    print("原始JSON响应:")
    print(answer)
    print()
    
    # 模拟_prepare_tts_text方法的处理
    try:
        parsed = json.loads(answer)
        # 为JSON添加时间ID
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        enhanced_json = {
            "id": current_time,
            **parsed  # 将原始JSON内容合并
        }
        # 生成增强后的JSON字符串
        enhanced_json_str = json.dumps(enhanced_json, ensure_ascii=False, indent=2)
        
        print("增强后的JSON (添加了时间ID):")
        print(enhanced_json_str)
        print()
        
        # 写入文件测试
        with open("test_model_command.txt", "w", encoding="utf-8") as f:
            f.write(enhanced_json_str)
        
        print("✅ JSON增强功能测试成功!")
        print(f"时间ID: {current_time}")
        print("文件已写入: test_model_command.txt")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")

if __name__ == "__main__":
    test_json_enhancement()

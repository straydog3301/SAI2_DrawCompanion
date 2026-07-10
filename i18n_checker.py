"""
i18n_checker.py - 國際化語系完整性檢查工具

檢查所有語系檔案的完整性，確保：
- 所有語言包含相同的鍵
- 沒有遺漏的翻譯
- 沒有多餘的鍵
- 格式正確
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Any

from logger import get_logger

logger = get_logger()

# 語系目錄
LOCALES_DIR = Path(__file__).parent / "locales"


class I18nChecker:
    """語系完整性檢查器"""
    
    def __init__(self, locales_dir: Path = None):
        self.locales_dir = locales_dir or LOCALES_DIR
        self.languages: Dict[str, Dict[str, Any]] = {}
        self.reference_lang = "zh_tw.json"  # 參考語言（繁體中文）
    
    def load_all_locales(self) -> bool:
        """載入所有語系檔案"""
        if not self.locales_dir.exists():
            logger.error(f"語系目錄不存在：{self.locales_dir}")
            return False
        
        loaded = 0
        for file in self.locales_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    self.languages[file.name] = json.load(f)
                loaded += 1
                logger.debug(f"已載入語系：{file.name}")
            except json.JSONDecodeError as e:
                logger.error(f"語系檔案 JSON 解析失敗 {file.name}: {e}")
            except Exception as e:
                logger.error(f"載入語系檔案失敗 {file.name}: {e}")
        
        logger.info(f"共載入 {loaded} 個語系檔案")
        return loaded > 0
    
    def get_all_keys(self, data: Dict, prefix: str = "") -> Set[str]:
        """遞迴取得所有鍵（扁平化）"""
        keys = set()
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                keys.update(self.get_all_keys(value, full_key))
            else:
                keys.add(full_key)
        return keys
    
    def check_missing_keys(self) -> Dict[str, List[str]]:
        """
        檢查各語言相對於參考語言遺漏的鍵
        
        Returns:
            Dict[language, [missing_keys]]
        """
        if self.reference_lang not in self.languages:
            logger.error(f"參考語言 {self.reference_lang} 未載入")
            return {}
        
        ref_keys = self.get_all_keys(self.languages[self.reference_lang])
        missing = {}
        
        for lang_name, lang_data in self.languages.items():
            if lang_name == self.reference_lang:
                continue
            
            lang_keys = self.get_all_keys(lang_data)
            missing_keys = ref_keys - lang_keys
            
            if missing_keys:
                missing[lang_name] = sorted(missing_keys)
        
        return missing
    
    def check_extra_keys(self) -> Dict[str, List[str]]:
        """
        檢查各語言相對於參考語言多餘的鍵
        
        Returns:
            Dict[language, [extra_keys]]
        """
        if self.reference_lang not in self.languages:
            return {}
        
        ref_keys = self.get_all_keys(self.languages[self.reference_lang])
        extra = {}
        
        for lang_name, lang_data in self.languages.items():
            if lang_name == self.reference_lang:
                continue
            
            lang_keys = self.get_all_keys(lang_data)
            extra_keys = lang_keys - ref_keys
            
            if extra_keys:
                extra[lang_name] = sorted(extra_keys)
        
        return extra
    
    def check_empty_values(self) -> Dict[str, List[str]]:
        """
        檢查空值的翻譯
        
        Returns:
            Dict[language, [empty_keys]]
        """
        empty = {}
        
        for lang_name, lang_data in self.languages.items():
            empty_keys = []
            
            def check_dict(d: Dict, prefix: str = ""):
                for key, value in d.items():
                    full_key = f"{prefix}.{key}" if prefix else key
                    if isinstance(value, dict):
                        check_dict(value, full_key)
                    elif value == "" or value is None:
                        empty_keys.append(full_key)
            
            check_dict(lang_data)
            
            if empty_keys:
                empty[lang_name] = sorted(empty_keys)
        
        return empty
    
    def check_format_consistency(self) -> Dict[str, List[str]]:
        """
        檢查格式一致性（例如：是否包含 {placeholder}）
        
        Returns:
            Dict[language, [inconsistent_keys]]
        """
        if self.reference_lang not in self.languages:
            return {}
        
        ref_data = self.languages[self.reference_lang]
        inconsistent = {}
        
        import re
        placeholder_pattern = re.compile(r'\{(\w+)\}')
        
        def get_placeholders(text: str) -> Set[str]:
            if not isinstance(text, str):
                return set()
            return set(placeholder_pattern.findall(text))
        
        def compare_values(ref: Dict, target: Dict, prefix: str = "") -> List[str]:
            issues = []
            
            for key, ref_value in ref.items():
                full_key = f"{prefix}.{key}" if prefix else key
                
                if key not in target:
                    continue
                
                target_value = target[key]
                
                if isinstance(ref_value, dict):
                    if isinstance(target_value, dict):
                        issues.extend(compare_values(ref_value, target_value, full_key))
                    else:
                        issues.append(full_key + " (類型不匹配)")
                elif isinstance(ref_value, str):
                    ref_placeholders = get_placeholders(ref_value)
                    if ref_placeholders:
                        target_placeholders = get_placeholders(target_value)
                        if ref_placeholders != target_placeholders:
                            issues.append(
                                f"{full_key} (佔位符不匹配：{ref_placeholders} vs {target_placeholders})"
                            )
            
            return issues
        
        for lang_name, lang_data in self.languages.items():
            if lang_name == self.reference_lang:
                continue
            
            issues = compare_values(ref_data, lang_data)
            if issues:
                inconsistent[lang_name] = issues
        
        return inconsistent
    
    def run_full_check(self) -> bool:
        """
        執行完整檢查
        
        Returns:
            bool: 是否通過所有檢查
        """
        print("=" * 60)
        print("SAI2 DrawCompanion - 語系完整性檢查")
        print("=" * 60)
        
        # 載入語系
        print("\n[1/5] 載入語系檔案...")
        if not self.load_all_locales():
            print("✗ 無法載入語系檔案")
            return False
        
        print(f"✓ 已載入 {len(self.languages)} 個語系:")
        for lang in self.languages:
            print(f"    - {lang}")
        
        all_passed = True
        
        # 檢查遺漏的鍵
        print("\n[2/5] 檢查遺漏的翻譯...")
        missing = self.check_missing_keys()
        if missing:
            all_passed = False
            print(f"✗ 發現 {len(missing)} 個語言有遺漏的鍵:")
            for lang, keys in missing.items():
                print(f"    {lang}: {len(keys)} 個遺漏")
                for key in keys[:5]:  # 只顯示前 5 個
                    print(f"      - {key}")
                if len(keys) > 5:
                    print(f"      ... 還有 {len(keys) - 5} 個")
        else:
            print("✓ 所有語言的鍵都完整")
        
        # 檢查多餘的鍵
        print("\n[3/5] 檢查多餘的鍵...")
        extra = self.check_extra_keys()
        if extra:
            all_passed = False
            print(f"✗ 發現 {len(extra)} 個語言有多餘的鍵:")
            for lang, keys in extra.items():
                print(f"    {lang}: {len(keys)} 個多餘")
                for key in keys[:5]:
                    print(f"      - {key}")
        else:
            print("✓ 沒有多餘的鍵")
        
        # 檢查空值
        print("\n[4/5] 檢查空值翻譯...")
        empty = self.check_empty_values()
        if empty:
            all_passed = False
            print(f"✗ 發現 {len(empty)} 個語言有空值:")
            for lang, keys in empty.items():
                print(f"    {lang}: {len(keys)} 個空值")
                for key in keys[:5]:
                    print(f"      - {key}")
        else:
            print("✓ 沒有空值翻譯")
        
        # 檢查格式一致性
        print("\n[5/5] 檢查格式一致性...")
        format_issues = self.check_format_consistency()
        if format_issues:
            all_passed = False
            print(f"✗ 發現 {len(format_issues)} 個語言有格式問題:")
            for lang, issues in format_issues.items():
                print(f"    {lang}: {len(issues)} 個問題")
                for issue in issues[:5]:
                    print(f"      - {issue}")
        else:
            print("✓ 格式一致")
        
        # 總結
        print("\n" + "=" * 60)
        if all_passed:
            print("✓ 所有檢查通過！")
        else:
            print("✗ 發現問題，請修正後再提交")
        print("=" * 60)
        
        return all_passed
    
    def generate_missing_template(self, output_path: Path = None) -> str:
        """
        產生遺漏鍵的模板，協助翻譯者快速補充
        
        Returns:
            JSON 字串格式的模板
        """
        missing = self.check_missing_keys()
        if not missing:
            return "{}"
        
        template = {}
        ref_data = self.languages[self.reference_lang]
        
        def get_nested_value(data: Dict, key_path: str) -> Any:
            keys = key_path.split(".")
            value = data
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return None
            return value
        
        for lang, missing_keys in missing.items():
            template[lang] = {}
            for key in missing_keys:
                value = get_nested_value(ref_data, key)
                
                # 設定到巢狀結構
                keys = key.split(".")
                current = template[lang]
                for k in keys[:-1]:
                    if k not in current:
                        current[k] = {}
                    current = current[k]
                current[keys[-1]] = value if value is not None else "TODO"
        
        output = json.dumps(template, ensure_ascii=False, indent=2)
        
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(output)
            logger.info(f"遺漏鍵模板已寫入：{output_path}")
        
        return output


def main():
    """主程式"""
    import argparse
    
    parser = argparse.ArgumentParser(description="語系完整性檢查工具")
    parser.add_argument(
        "--generate-template",
        type=str,
        help="產生遺漏鍵模板並儲存到指定路徑"
    )
    parser.add_argument(
        "--reference",
        type=str,
        default="zh_tw.json",
        help="參考語言檔案（預設：zh_tw.json）"
    )
    parser.add_argument(
        "--locales-dir",
        type=str,
        help="語系目錄路徑（預設：./locales）"
    )
    
    args = parser.parse_args()
    
    checker = I18nChecker(
        locales_dir=Path(args.locales_dir) if args.locales_dir else None
    )
    checker.reference_lang = args.reference
    
    if args.generate_template:
        checker.load_all_locales()
        template = checker.generate_missing_template(Path(args.generate_template))
        print(f"\n模板已產生：{args.generate_template}")
        print(template[:500] + "..." if len(template) > 500 else template)
    else:
        success = checker.run_full_check()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
批量恢复 importance >= 5 的归档桶。

用法：
  python tools/restore_important_archived.py [--dry-run] [--min-importance 5]

  --dry-run         只打印会恢复哪些桶，不实际操作
  --min-importance   最低重要度阈值（默认 5）

原因：
  2026-11-24 修改了衰减引擎，importance >= 5 的桶不再参与衰减。
  但在此之前已经有大量高重要度的桶被错误归档了，需要批量恢复。

安全措施：
  - 跳过 protected/anchor 桶（恢复时有冲突需要手动处理）
  - 恢复后刷新 last_active 防止立即二次归档
  - 先统计再确认再执行
"""

import os
import sys
import argparse
import frontmatter

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from utils import parse_bool


def find_archived_buckets(archive_dir: str, min_importance: int) -> list[dict]:
    """扫描归档目录，找出 importance >= min_importance 的桶。"""
    candidates = []
    if not os.path.isdir(archive_dir):
        print(f"归档目录不存在: {archive_dir}")
        return candidates

    for dirpath, _, filenames in os.walk(archive_dir):
        for fname in filenames:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                post = frontmatter.load(fpath)
            except Exception as e:
                print(f"  跳过（读取失败）: {fpath} - {e}")
                continue

            meta = dict(post.metadata)
            bucket_id = meta.get("id", fname.replace(".md", ""))

            # 跳过 protected/anchor（恢复有冲突）
            if parse_bool(meta.get("protected"), default=False):
                continue
            if parse_bool(meta.get("anchor"), default=False):
                continue

            try:
                imp = int(meta.get("importance", 0))
            except (TypeError, ValueError):
                imp = 0

            if imp >= min_importance:
                candidates.append({
                    "id": bucket_id,
                    "name": meta.get("name", ""),
                    "title": meta.get("title", ""),
                    "importance": imp,
                    "domain": meta.get("domain", ""),
                    "path": fpath,
                })

    return candidates


def main():
    parser = argparse.ArgumentParser(description="批量恢复高重要度归档桶")
    parser.add_argument("--dry-run", action="store_true", help="只打印不执行")
    parser.add_argument("--min-importance", type=int, default=5, help="最低重要度（默认5）")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="数据目录（默认从环境变量 OMBRE_DATA_DIR 或 ./data）")
    args = parser.parse_args()

    data_dir = args.data_dir or os.environ.get("OMBRE_DATA_DIR", os.path.join(ROOT, "data"))
    archive_dir = os.path.join(data_dir, "archive")

    print(f"扫描归档目录: {archive_dir}")
    print(f"最低重要度: {args.min_importance}")
    print()

    candidates = find_archived_buckets(archive_dir, args.min_importance)

    if not candidates:
        print("没有找到符合条件的归档桶。")
        return

    print(f"找到 {len(candidates)} 个 importance >= {args.min_importance} 的归档桶：")
    print("-" * 80)
    for c in sorted(candidates, key=lambda x: -x["importance"]):
        display = c["title"] or c["name"] or c["id"]
        print(f"  imp={c['importance']:2d}  {display}")
    print("-" * 80)

    if args.dry_run:
        print(f"\n[DRY RUN] 以上 {len(candidates)} 个桶将被恢复。加 --no-dry-run 执行。")
        return

    confirm = input(f"\n确认恢复以上 {len(candidates)} 个桶？(y/N) ")
    if confirm.lower() != "y":
        print("已取消。")
        return

    # 恢复逻辑：把桶从 archive 移回对应的 channel 目录
    buckets_dir = os.path.join(data_dir, "buckets")
    restored = 0
    failed = 0

    for c in candidates:
        try:
            post = frontmatter.load(c["path"])

            # 恢复 type
            original_type = "dynamic"
            if parse_bool(post.get("pinned"), default=False):
                original_type = "permanent"
            post["type"] = original_type
            post["pinned"] = False

            # 清除归档标记
            for field in ("deleted_at", "tombstone", "tombstoned_at", "erasure_mode"):
                post.metadata.pop(field, None)

            # 刷新活跃时间
            from datetime import datetime, timezone
            post["last_active"] = datetime.now(timezone.utc).isoformat()

            # 确定目标目录
            domain = post.get("domain")
            if isinstance(domain, list):
                domain_name = domain[0] if domain else "general"
            elif isinstance(domain, str):
                domain_name = domain or "general"
            else:
                domain_name = "general"

            target_dir = os.path.join(buckets_dir, domain_name)
            os.makedirs(target_dir, exist_ok=True)

            target_path = os.path.join(target_dir, os.path.basename(c["path"]))

            # 写入新位置
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(frontmatter.dumps(post))

            # 删除归档位置的文件
            os.remove(c["path"])

            restored += 1
            display = c["title"] or c["name"] or c["id"]
            print(f"  ✓ 恢复: {display}")

        except Exception as e:
            failed += 1
            print(f"  ✗ 失败: {c['id']} - {e}")

    print(f"\n完成：恢复 {restored} 个，失败 {failed} 个。")


if __name__ == "__main__":
    main()

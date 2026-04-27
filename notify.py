#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import os
import smtplib
import socket
import subprocess
import time
from dataclasses import dataclass
from email.mime.text import MIMEText
from email.header import Header
from typing import Dict, List


@dataclass
class GPUStatus:
    index: int
    name: str
    memory_used_mib: int
    memory_total_mib: int
    utilization_gpu: int
    process_count: int


def run_command(cmd: List[str]) -> str:
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    return result.stdout


def get_gpu_statuses() -> Dict[int, GPUStatus]:
    """
    nvidia-smiからGPUごとの使用状況を取得する。
    """
    query_cmd = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]

    output = run_command(query_cmd)

    statuses: Dict[int, GPUStatus] = {}

    reader = csv.reader(output.strip().splitlines())
    for row in reader:
        index = int(row[0].strip())
        name = row[1].strip()
        memory_used_mib = int(row[2].strip())
        memory_total_mib = int(row[3].strip())
        utilization_gpu = int(row[4].strip())

        statuses[index] = GPUStatus(
            index=index,
            name=name,
            memory_used_mib=memory_used_mib,
            memory_total_mib=memory_total_mib,
            utilization_gpu=utilization_gpu,
            process_count=0,
        )

    # GPUごとのプロセス数も取得
    process_cmd = [
        "nvidia-smi",
        "--query-compute-apps=gpu_uuid,pid,used_memory",
        "--format=csv,noheader,nounits",
    ]

    # GPU UUID -> index の対応を取得
    uuid_cmd = [
        "nvidia-smi",
        "--query-gpu=index,uuid",
        "--format=csv,noheader,nounits",
    ]

    uuid_output = run_command(uuid_cmd)
    uuid_to_index = {}

    reader = csv.reader(uuid_output.strip().splitlines())
    for row in reader:
        index = int(row[0].strip())
        uuid = row[1].strip()
        uuid_to_index[uuid] = index

    try:
        process_output = run_command(process_cmd)
        if process_output.strip():
            reader = csv.reader(process_output.strip().splitlines())
            for row in reader:
                gpu_uuid = row[0].strip()
                if gpu_uuid in uuid_to_index:
                    gpu_index = uuid_to_index[gpu_uuid]
                    statuses[gpu_index].process_count += 1
    except subprocess.CalledProcessError:
        # プロセスがない場合などでも落とさない
        pass

    return statuses


def is_gpu_free(
    status: GPUStatus,
    max_memory_used_mib: int,
    max_gpu_util: int,
    require_no_process: bool,
) -> bool:
    """
    GPUが空いているか判定する。
    """
    if status.memory_used_mib > max_memory_used_mib:
        return False

    if status.utilization_gpu > max_gpu_util:
        return False

    if require_no_process and status.process_count > 0:
        return False

    return True


def send_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    mail_from: str,
    mail_to: str,
    subject: str,
    body: str,
    use_ssl: bool = False,
):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = mail_from
    msg["To"] = mail_to

    if use_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)


def main():
    parser = argparse.ArgumentParser(
        description="Monitor GPU availability and send an email notification."
    )

    parser.add_argument(
        "--gpu",
        type=int,
        required=True,
        help="監視するGPU index。例: 0",
    )
    parser.add_argument(
        "--to",
        type=str,
        required=True,
        help="通知先メールアドレス",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="監視間隔 [秒]",
    )
    parser.add_argument(
        "--free-duration",
        type=int,
        default=300,
        help="この秒数だけ空き状態が続いたら通知する",
    )
    parser.add_argument(
        "--max-memory-used-mib",
        type=int,
        default=500,
        help="空きとみなす最大メモリ使用量 [MiB]",
    )
    parser.add_argument(
        "--max-gpu-util",
        type=int,
        default=5,
        help="空きとみなす最大GPU使用率 [%]",
    )
    parser.add_argument(
        "--allow-process",
        action="store_true",
        help="指定するとプロセスが存在してもメモリ/使用率が低ければ空きとみなす",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="通知を送ったら終了する",
    )

    args = parser.parse_args()

    smtp_host = os.environ.get("GPU_NOTIFY_SMTP_HOST")
    smtp_port = int(os.environ.get("GPU_NOTIFY_SMTP_PORT", "587"))
    smtp_user = os.environ.get("GPU_NOTIFY_SMTP_USER")
    smtp_password = os.environ.get("GPU_NOTIFY_SMTP_PASSWORD")
    mail_from = os.environ.get("GPU_NOTIFY_FROM", smtp_user)
    use_ssl = os.environ.get("GPU_NOTIFY_USE_SSL", "0") == "1"

    if not smtp_host or not smtp_user or not smtp_password or not mail_from:
        raise RuntimeError(
            "SMTP設定が不足しています。\n"
            "以下の環境変数を設定してください:\n"
            "  GPU_NOTIFY_SMTP_HOST\n"
            "  GPU_NOTIFY_SMTP_PORT\n"
            "  GPU_NOTIFY_SMTP_USER\n"
            "  GPU_NOTIFY_SMTP_PASSWORD\n"
            "  GPU_NOTIFY_FROM"
        )

    hostname = socket.gethostname()

    free_since = None
    already_notified = False

    print(f"Start monitoring: host={hostname}, GPU={args.gpu}")
    print(f"Check interval: {args.interval} sec")
    print(f"Free duration threshold: {args.free_duration} sec")

    while True:
        try:
            statuses = get_gpu_statuses()

            if args.gpu not in statuses:
                raise RuntimeError(f"GPU {args.gpu} が見つかりません。")

            status = statuses[args.gpu]

            free = is_gpu_free(
                status=status,
                max_memory_used_mib=args.max_memory_used_mib,
                max_gpu_util=args.max_gpu_util,
                require_no_process=not args.allow_process,
            )

            now = time.time()

            print(
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"GPU {status.index}: {status.name}, "
                f"mem={status.memory_used_mib}/{status.memory_total_mib} MiB, "
                f"util={status.utilization_gpu}%, "
                f"processes={status.process_count}, "
                f"free={free}"
            )

            if free:
                if free_since is None:
                    free_since = now

                free_elapsed = now - free_since

                if free_elapsed >= args.free_duration and not already_notified:
                    subject = f"[GPU空き通知] {hostname} の GPU {args.gpu} が空きました"

                    body = f"""GPUが空いた可能性があります。

Machine: {hostname}
GPU: {status.index}
GPU name: {status.name}

Memory used: {status.memory_used_mib} MiB / {status.memory_total_mib} MiB
GPU utilization: {status.utilization_gpu} %
Process count: {status.process_count}

判定条件:
- memory.used <= {args.max_memory_used_mib} MiB
- utilization.gpu <= {args.max_gpu_util} %
- process_count == 0: {not args.allow_process}
- free duration >= {args.free_duration} sec
"""

                    send_email(
                        smtp_host=smtp_host,
                        smtp_port=smtp_port,
                        smtp_user=smtp_user,
                        smtp_password=smtp_password,
                        mail_from=mail_from,
                        mail_to=args.to,
                        subject=subject,
                        body=body,
                        use_ssl=use_ssl,
                    )

                    print("Notification email sent.")
                    already_notified = True

                    if args.once:
                        break

            else:
                # 使用中に戻ったらリセット
                free_since = None
                already_notified = False

        except Exception as e:
            print(f"Error: {e}")

        time.sleep(args.interval)


if __name__ == "__main__":
    main()


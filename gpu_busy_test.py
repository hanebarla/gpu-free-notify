#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import time

import torch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=300, help="GPUを使い続ける秒数")
    parser.add_argument("--gpu", type=int, default=0, help="使用するGPU index")
    parser.add_argument("--size", type=int, default=4096, help="行列サイズ")
    parser.add_argument("--sleep", type=float, default=0.0, help="各計算ループ後のsleep秒数")
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDAが利用できません。")

    device = torch.device(f"cuda:{args.gpu}")
    torch.cuda.set_device(device)

    print(f"Use device: {device}")
    print(f"Run for {args.seconds} seconds")
    print(f"Matrix size: {args.size} x {args.size}")

    # GPUメモリを確保
    a = torch.randn((args.size, args.size), device=device)
    b = torch.randn((args.size, args.size), device=device)

    start = time.time()
    count = 0

    while time.time() - start < args.seconds:
        # GPUで重めの行列積を実行
        c = torch.matmul(a, b)

        # 計算が遅延実行のままにならないように同期
        torch.cuda.synchronize(device)

        # cが最適化で消されないように少し使う
        value = c[0, 0].item()

        count += 1

        if count % 10 == 0:
            elapsed = time.time() - start
            print(f"elapsed={elapsed:.1f}s, iter={count}, value={value:.6f}")

        if args.sleep > 0:
            time.sleep(args.sleep)

    print("Done.")


if __name__ == "__main__":
    main()

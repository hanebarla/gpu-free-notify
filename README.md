# gpu-free-notify

## 使い方
例：GmailのSMTPを使う場合
```sh
export GPU_NOTIFY_SMTP_HOST="smtp.gmail.com"
export GPU_NOTIFY_SMTP_PORT="587"
export GPU_NOTIFY_SMTP_USER="your_account@gmail.com"
export GPU_NOTIFY_SMTP_PASSWORD="your_app_password"
export GPU_NOTIFY_FROM="your_account@gmail.com"
```

Gmailの場合、通常のログインパスワードではなくアプリパスワードを使う必要があります。

そのうえで、例えばGPU 2を監視するなら、
```sh
python gpu_free_notifier.py \
  --gpu 2 \
  --to your_address@example.com \
  --interval 60 \
  --free-duration 300 \
  --max-memory-used-mib 500 \
  --max-gpu-util 5
```

この例では、
- 60秒ごとに確認
- GPU 2のメモリ使用量が500 MiB以下
- GPU使用率が5%以下
- 実行中プロセスが0個
- その状態が5分続く

という条件を満たしたときに、メールを送ります。

## 複数のGPUを監視する場合
GPUごとに別プロセスで起動する
```sh
python gpu_free_notifier.py --gpu 0 --to your_address@example.com &
python gpu_free_notifier.py --gpu 1 --to your_address@example.com &
python gpu_free_notifier.py --gpu 2 --to your_address@example.com &
python gpu_free_notifier.py --gpu 3 --to your_address@example.com &
```

## systemdやtmuxで常駐させる場合
tmuxの場合
```sh
tmux new -s gpu_notify
```
中で以下を実行
```sh
python gpu_free_notifier.py \
  --gpu 0 \
  --to your_address@example.com \
  --interval 60 \
  --free-duration 300
```

## 判定条件について
他人の実験が終わったかどうかを判定するなら、基本は
```sh
process_count == 0
```
を見るのが安全。

ただし、PyTorchなどではプロセスが残ったままGPUメモリを少しだけ保持していることもあります。そのため、現実的には以下のような条件が良いです。
```sh
--max-memory-used-mib 500
--max-gpu-util 5
```
厳しめに判定するなら、
```sh
--max-memory-used-mib 100
--max-gpu-util 0
```

一方、X serverやdisplay関係で常に少量のGPUメモリを使っている環境では、`100 MiB`だと厳しすぎることがあります。その場合は`500 MiB`から`1000 MiB`程度にするとよいです。

## GPUをとりあえず動かすコード
例：GPU0を5分間使用する場合
```sh
python gpu_busy_test.py --gpu 0 --seconds 300
```

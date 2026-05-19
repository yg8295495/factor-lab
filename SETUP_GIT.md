# Git 远程仓库配置

## 前置条件
在 Gitee/GitHub 上创建同名仓库 `factor-lab`（**不要勾选** 初始化 README）。

## 推送命令

### 方案A：Gitee 主力 + GitHub 备份（推荐）

```bash
cd factor-lab

# 1. 先加 Gitee
git remote add origin https://gitee.com/sunshine85/factor-lab.git

# 2. 再加 GitHub
git remote set-url --add origin https://github.com/yg8295495/factor-lab.git

# 3. 推送（自动走两个地址）
git push -u origin master
```

### 方案B：拆成两个独立 remote（推荐，更清楚）

```bash
cd factor-lab

git remote add origin https://gitee.com/sunshine85/factor-lab.git
git remote add github https://github.com/yg8295495/factor-lab.git

git push origin master
git push -u github master
```

## macOS 上克隆

```bash
git clone https://gitee.com/sunshine85/factor-lab.git
cd factor-lab
python backend/rebuild_db.py    # 重建数据库
# 开工
```

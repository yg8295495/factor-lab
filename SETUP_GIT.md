# Git 远程仓库配置

## 前置条件
在 Gitee/GitHub 上创建同名仓库 `factor-lab`（**不要勾选** 初始化 README）。

## 推送命令

### 方案A：Gitee 主力 + GitHub 备份（推荐）

```bash
cd factor-lab

# 添加 Gitee 远程（主力）
git remote add origin https://gitee.com/你的用户名/factor-lab.git

# 推送
git push -u origin master

# 添加 GitHub 远程（备份）
git remote set-url --add origin https://github.com/你的用户名/factor-lab.git

# 以后 git push 会自动推两个地址
```

### 方案B：只用 Gitee

```bash
cd factor-lab
git remote add origin https://gitee.com/你的用户名/factor-lab.git
git push -u origin master
```

## macOS 上克隆

```bash
git clone https://gitee.com/你的用户名/factor-lab.git
cd factor-lab
python backend/rebuild_db.py    # 重建数据库（.gitignore 排除了 db 文件）
# 开工
```

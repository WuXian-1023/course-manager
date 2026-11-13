[app]
# Android 打包配置：应用包名保持不变，确保未来可覆盖安装更新。
title = 课程记录与工资管理
package.name = coursemanager
package.domain = org.localcourse
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,ttf,otf,ttc
source.exclude_dirs = .git,__pycache__,.venv,venv,build,dist
version = 1.0.0
requirements = python3,kivy,openpyxl
p4a.branch = develop
orientation = portrait
fullscreen = 0

# 课程数据保存在应用私有目录；联网仅用于检查 GitHub 更新。
android.permissions = INTERNET
android.api = 35
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = True
android.private_storage = True

# 保留原项目资源路径；请确认这两个图片文件在 assets 目录中存在。
presplash.filename = %(source.dir)s/assets/preplash.png
icon.filename = %(source.dir)s/assets/icon.png

[buildozer]
log_level = 2
warn_on_root = 1

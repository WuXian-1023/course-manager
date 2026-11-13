from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path
import math

# 使用高分辨率绘制，再缩小，提高图标边缘质量
SCALE = 4
SIZE = 1024
W = SIZE * SCALE

output_dir = Path("assets")
output_dir.mkdir(exist_ok=True)
output_path = output_dir / "icon.png"


def sc(v):
    return int(v * SCALE)


def rounded_rectangle(draw, box, radius, fill, outline=None, width=1):
    box = tuple(sc(x) for x in box)
    draw.rounded_rectangle(
        box,
        radius=sc(radius),
        fill=fill,
        outline=outline,
        width=sc(width)
    )


# 创建透明画布
img = Image.new("RGBA", (W, W), (0, 0, 0, 0))

# -------------------------
# 背景和阴影
# -------------------------
shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
shadow_draw = ImageDraw.Draw(shadow)

rounded_rectangle(
    shadow_draw,
    (90, 105, 934, 949),
    190,
    (0, 0, 0, 95)
)

shadow = shadow.filter(ImageFilter.GaussianBlur(sc(28)))
img.alpha_composite(shadow, (0, sc(18)))

draw = ImageDraw.Draw(img)

# 主背景
rounded_rectangle(
    draw,
    (70, 70, 954, 954),
    200,
    (32, 91, 178, 255)
)

# 背景装饰圆
draw.ellipse(
    (sc(635), sc(20), sc(1060), sc(445)),
    fill=(72, 139, 224, 90)
)

draw.ellipse(
    (sc(-130), sc(680), sc(230), sc(1040)),
    fill=(19, 65, 143, 90)
)

# -------------------------
# 日历主体
# -------------------------
calendar_x1, calendar_y1 = 190, 190
calendar_x2, calendar_y2 = 834, 815

# 日历阴影
rounded_rectangle(
    draw,
    (calendar_x1 + 18, calendar_y1 + 22, calendar_x2 + 18, calendar_y2 + 22),
    55,
    (0, 35, 95, 90)
)

# 日历白色主体
rounded_rectangle(
    draw,
    (calendar_x1, calendar_y1, calendar_x2, calendar_y2),
    55,
    (249, 252, 255, 255)
)

# 日历顶部蓝色区域
rounded_rectangle(
    draw,
    (calendar_x1, calendar_y1, calendar_x2, 385),
    55,
    (42, 111, 207, 255)
)

# 遮住顶部下方圆角，保持底部平整
draw.rectangle(
    (sc(calendar_x1), sc(320), sc(calendar_x2), sc(385)),
    fill=(42, 111, 207, 255)
)

# 装订环
for x in (315, 709):
    draw.rounded_rectangle(
        (sc(x - 24), sc(145), sc(x + 24), sc(245)),
        radius=sc(20),
        fill=(255, 255, 255, 255)
    )
    draw.rounded_rectangle(
        (sc(x - 11), sc(168), sc(x + 11), sc(228)),
        radius=sc(10),
        fill=(42, 111, 207, 255)
    )

# 日历分隔线
draw.line(
    (sc(245), sc(405), sc(779), sc(405)),
    fill=(219, 228, 240, 255),
    width=sc(6)
)

# -------------------------
# 日历中的课程格子
# -------------------------
dot_colors = [
    (74, 144, 226, 255),
    (73, 177, 128, 255),
    (246, 174, 67, 255),
]

start_x = 270
start_y = 465
gap_x = 105
gap_y = 88
dot_radius = 18

for row in range(3):
    for col in range(5):
        color = dot_colors[(row + col) % len(dot_colors)]
        cx = start_x + col * gap_x
        cy = start_y + row * gap_y

        draw.ellipse(
            (
                sc(cx - dot_radius),
                sc(cy - dot_radius),
                sc(cx + dot_radius),
                sc(cy + dot_radius)
            ),
            fill=color
        )

# -------------------------
# 时钟主体
# -------------------------
clock_cx, clock_cy = 675, 680
clock_r = 175

# 时钟阴影
draw.ellipse(
    (
        sc(clock_cx - clock_r + 12),
        sc(clock_cy - clock_r + 18),
        sc(clock_cx + clock_r + 12),
        sc(clock_cy + clock_r + 18)
    ),
    fill=(0, 32, 85, 85)
)

# 时钟外圈
draw.ellipse(
    (
        sc(clock_cx - clock_r),
        sc(clock_cy - clock_r),
        sc(clock_cx + clock_r),
        sc(clock_cy + clock_r)
    ),
    fill=(255, 255, 255, 255)
)

# 时钟蓝色内圈
draw.ellipse(
    (
        sc(clock_cx - clock_r + 18),
        sc(clock_cy - clock_r + 18),
        sc(clock_cx + clock_r - 18),
        sc(clock_cy + clock_r - 18)
    ),
    fill=(235, 245, 255, 255)
)

# 时钟刻度
for i in range(12):
    angle = math.radians(i * 30 - 90)
    outer = clock_r - 35
    inner = clock_r - 55

    x1 = clock_cx + math.cos(angle) * inner
    y1 = clock_cy + math.sin(angle) * inner
    x2 = clock_cx + math.cos(angle) * outer
    y2 = clock_cy + math.sin(angle) * outer

    draw.line(
        (sc(x1), sc(y1), sc(x2), sc(y2)),
        fill=(42, 111, 207, 255),
        width=sc(9)
    )

# 时针：指向 10 点
draw.line(
    (sc(clock_cx), sc(clock_cy), sc(clock_cx - 58), sc(clock_cy - 44)),
    fill=(24, 67, 130, 255),
    width=sc(18)
)

# 分针：指向 2 点
draw.line(
    (sc(clock_cx), sc(clock_cy), sc(clock_cx + 62), sc(clock_cy - 74)),
    fill=(24, 67, 130, 255),
    width=sc(18)
)

# 中心圆点
draw.ellipse(
    (
        sc(clock_cx - 18),
        sc(clock_cy - 18),
        sc(clock_cx + 18),
        sc(clock_cy + 18)
    ),
    fill=(42, 111, 207, 255)
)

# -------------------------
# 右下角完成对勾
# -------------------------
check_points = [
    (760, 790),
    (810, 842),
    (908, 735)
]

# 对勾背景圆
draw.ellipse(
    (sc(705), sc(700), sc(960), sc(955)),
    fill=(30, 167, 112, 255),
    outline=(255, 255, 255, 255),
    width=sc(10)
)

# 对勾
draw.line(
    [
        (sc(760), sc(815)),
        (sc(810), sc(865)),
        (sc(902), sc(765))
    ],
    fill=(255, 255, 255, 255),
    width=sc(27),
    joint="curve"
)

# 缩小为 Android 常用图标尺寸
img = img.resize((1024, 1024), Image.Resampling.LANCZOS)

# 保存
img.save(output_path, "PNG", optimize=True)

print(f"图标已生成：{output_path.resolve()}")


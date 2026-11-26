"""Draws the Video Saver icon: a play button over a down arrow into a tray, on a blue tile."""
import sys
from PIL import Image, ImageDraw, ImageFilter

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
tile = Image.new("RGBA", (S, S))
g = ImageDraw.Draw(tile)
top, bottom = (64, 150, 245), (20, 70, 170)
for y in range(S):
    t = y / S
    g.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([100, 100, 924, 924], radius=185, fill=255)
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle([100, 118, 924, 942], radius=185, fill=(0, 0, 0, 90))
img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
img.paste(tile, (0, 0), mask)

d = ImageDraw.Draw(img)
W = (255, 255, 255, 255)
# video card with a play triangle
d.rounded_rectangle([262, 214, 762, 524], radius=60, fill=W)
d.polygon([(460, 298), (460, 440), (580, 369)], fill=(30, 95, 200, 255))
# down arrow
d.rectangle([482, 548, 542, 660], fill=W)
d.polygon([(410, 640), (614, 640), (512, 742)], fill=W)
# tray (the Finder folder it lands in)
d.rounded_rectangle([262, 690, 312, 810], radius=24, fill=W)
d.rounded_rectangle([712, 690, 762, 810], radius=24, fill=W)
d.rounded_rectangle([262, 762, 762, 810], radius=24, fill=W)
img.save(sys.argv[1])

import ast
import sys

print("  python", sys.version.split()[0])
src = 'x = f"A{len(sim.snow_fields)}B"\n'
print("  源码:", repr(src.strip()))
line = src.splitlines()[0]
t = ast.parse(src)
for n in ast.walk(t):
    if isinstance(n, (ast.Attribute, ast.Name)):
        label = n.attr if isinstance(n, ast.Attribute) else n.id
        kind = "Attribute" if isinstance(n, ast.Attribute) else "Name"
        cut = line[n.col_offset:n.end_col_offset]
        flag = "  ← ✅" if cut == label else "  ← ❌ 切错了"
        print("  %-9s %-14r lineno=%d col=%d end=%d  切出 %r%s"
              % (kind, label, n.lineno, n.col_offset, n.end_col_offset, cut, flag))

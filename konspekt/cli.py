"""Командная строка прототипа.

    python -m konspekt template бланк.pdf
    python -m konspekt import "Мой почерк" скан1.pdf фото2.jpg --profiles profiles
    python -m konspekt report "Мой почерк"
    python -m konspekt render "Мой почерк" текст.txt конспект.pdf --paper grid --seed 3
"""

import argparse
import sys
from pathlib import Path

from . import layout as lay
from .extract import ImportErrorRu, import_files
from .profile import Profile, safe_folder_name
from .render import render, save_pdf, save_pngs
from .service import INK_COLORS, INKS
from .template import TEMPLATE_SETS, save_template_pdf


def _profile_dir(args, name: str) -> Path:
    p = Path(name)
    if (p / "profile.json").exists():
        return p
    return Path(args.profiles) / safe_folder_name(name)


def cmd_template(args) -> int:
    n = save_template_pdf(args.out, args.set)
    print(f"Бланк «{TEMPLATE_SETS[args.set].title}» сохранён: {args.out} ({n} стр.). "
          "Распечатайте, заполните ручкой и отсканируйте.")
    return 0


def cmd_import(args) -> int:
    root = _profile_dir(args, args.profile)
    prof = Profile.load(root) if (root / "profile.json").exists() else Profile.create(root, args.profile)
    files = []
    for f in args.files:
        if Path(f).exists() and prof.is_imported(f):
            print(f"Пропущен, уже импортирован раньше: {f}")
        else:
            files.append(f)
    if not files:
        print("Новых файлов нет.")
        return 0
    rep = import_files(files)
    if rep.files_without_markers:
        print("Не найдены метки бланка (лист должен быть виден целиком, все 4 угловых квадрата):")
        for f in rep.files_without_markers:
            print("  -", f)
    added = prof.add_extracted(rep.samples)
    for f in files:
        prof.mark_imported(f)
    prof.save()
    pages = ", ".join(str(p + 1) for p in sorted(set(rep.pages_found))) or "нет"
    print(f"Профиль «{prof.name}»: найдено страниц бланка: {pages}; добавлено образцов: {len(added)}; "
          f"пустых клеток: {rep.empty_cells}")
    print(f"Высота строчных: {prof.params.x_height_mm} мм, толщина линии: {prof.params.stroke_mm} мм")
    return 0 if added else 1


def cmd_report(args) -> int:
    prof = Profile.load(_profile_dir(args, args.profile))
    print(f"Профиль «{prof.name}»: {len(prof.samples)} образцов")
    for group, info in prof.coverage().items():
        if group == "стоит добавить":
            line = (f"  мало вариантов у частых букв (меньше 6): {info}. Заполните ещё раз "
                    "дополнительный бланк" if info else "  частых букв достаточно")
        elif isinstance(info, dict):
            line = f"  {group}: нет — {info['нет'] or '—'}; только один вариант — {info['один вариант'] or '—'}"
        else:
            line = f"  {group}: {', '.join(info) or '—'}"
        print(line)
    return 0


def cmd_render(args) -> int:
    prof = Profile.load(_profile_dir(args, args.profile))
    text = Path(args.text).read_text(encoding="utf-8-sig")
    s = lay.Settings(page=args.page, paper=args.paper, dpi=args.dpi, seed=args.seed,
                     neatness=args.neatness, x_height_mm=args.size, line_pitch_mm=args.pitch,
                     highlight_missing=args.show_missing, smoothness=args.smooth, weight=args.weight,
                     ink_color=INK_COLORS.get(args.ink))
    layout = lay.typeset(text, prof, s)
    images = render(layout, prof)
    out = Path(args.out)
    if out.suffix.lower() == ".pdf":
        save_pdf(images, out, s.dpi)
    else:
        save_pngs(images, out)
    print(f"Готово: {out} ({len(images)} стр.)")
    if layout.missing:
        print("Нет образцов для символов (взяты из запасного шрифта): " + " ".join(sorted(layout.missing)))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="konspekt", description="Рукописные конспекты по образцам почерка")
    ap.add_argument("--profiles", default="profiles", help="папка с профилями почерков")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("template", help="создать бланк образцов (PDF)")
    t.add_argument("out")
    t.add_argument("--set", default="main", choices=list(TEMPLATE_SETS),
                   help="main — основной бланк, extra — дополнительный (больше вариантов частых букв, слова)")
    t.set_defaults(func=cmd_template)

    i = sub.add_parser("import", help="добавить образцы из заполненного бланка в профиль")
    i.add_argument("profile", help="имя профиля или путь к его папке")
    i.add_argument("files", nargs="+", help="сканы или фото (PDF, JPG, PNG)")
    i.set_defaults(func=cmd_import)

    r = sub.add_parser("report", help="какие символы есть в профиле")
    r.add_argument("profile")
    r.set_defaults(func=cmd_report)

    g = sub.add_parser("render", help="сгенерировать конспект")
    g.add_argument("profile")
    g.add_argument("text", help="текстовый файл UTF-8")
    g.add_argument("out", help="PDF или PNG")
    g.add_argument("--page", default="A4", choices=["A4", "A5"])
    g.add_argument("--paper", default="grid", choices=["grid", "lines", "blank"])
    g.add_argument("--dpi", type=int, default=200)
    g.add_argument("--seed", type=int, default=1, help="другое число — другой вариант оформления")
    g.add_argument("--neatness", type=float, default=1.0, help="0.5 аккуратнее, 1.5 небрежнее")
    g.add_argument("--size", type=float, default=None, help="высота строчных, мм")
    g.add_argument("--pitch", type=float, default=10.0, help="расстояние между строками, мм")
    g.add_argument("--show-missing", action="store_true", help="подсветить символы без образцов")
    g.add_argument("--smooth", type=float, default=0.5, help="гладкость линии: 0 как в скане, 1 ровно")
    g.add_argument("--weight", type=float, default=1.0, help="толщина линии: 1 как на скане, 0.5 тоньше, 2 толще")
    g.add_argument("--ink", default="", choices=[k for k, _ in INKS], help="цвет ручки: black — чёрная")
    g.set_defaults(func=cmd_render)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (ImportErrorRu, FileNotFoundError, FileExistsError, ValueError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

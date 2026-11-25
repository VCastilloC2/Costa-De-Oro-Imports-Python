"""Small dependency-free PDF and XLSX exports for the dashboard sales report."""
from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


def _cop(value: float | int) -> str:
    return f"{round(float(value)):,}".replace(",", ".")


def _pdf_string(value: str) -> bytes:
    raw = value.encode("cp1252", errors="replace")
    escaped = bytearray(b"(")
    for char in raw:
        if char in (ord("("), ord(")"), ord("\\")):
            escaped.extend(b"\\" + bytes((char,)))
        elif char < 32 or char > 126:
            escaped.extend(f"\\{char:03o}".encode("ascii"))
        else:
            escaped.append(char)
    escaped.append(ord(")"))
    return bytes(escaped)


def build_sales_pdf(report: Any, months: int) -> bytes:
    today = date.today().strftime("%d/%m/%Y")
    total = float(report.totalMonto)
    commands = [
        "BT /F1 22 Tf 48 786 Td " + _pdf_string("Reporte de ventas totales").decode("latin1") + " Tj ET",
        "BT /F1 11 Tf 48 762 Td " + _pdf_string(f"Periodo: últimos {months} meses    Generado: {today}").decode("latin1") + " Tj ET",
        "0.78 w 48 744 m 547 744 l S",
        "BT /F1 14 Tf 48 712 Td " + _pdf_string(f"Total del periodo: $ {_cop(total)} COP").decode("latin1") + " Tj ET",
        "BT /F1 10 Tf 48 672 Td " + _pdf_string("Estado").decode("latin1") + " Tj ET",
        "BT /F1 10 Tf 288 672 Td " + _pdf_string("Pedidos").decode("latin1") + " Tj ET",
        "BT /F1 10 Tf 365 672 Td " + _pdf_string("Monto (COP)").decode("latin1") + " Tj ET",
        "BT /F1 10 Tf 480 672 Td " + _pdf_string("Participación").decode("latin1") + " Tj ET",
        "0.5 w 48 660 m 547 660 l S",
    ]
    y = 636
    for item in report.items:
        share = (float(item.monto) / total * 100) if total else 0
        commands.extend([
            f"BT /F1 11 Tf 48 {y} Td " + _pdf_string(item.nombre).decode("latin1") + " Tj ET",
            f"BT /F1 11 Tf 288 {y} Td " + _pdf_string(str(item.pedidos)).decode("latin1") + " Tj ET",
            f"BT /F1 11 Tf 365 {y} Td " + _pdf_string("$ " + _cop(item.monto)).decode("latin1") + " Tj ET",
            f"BT /F1 11 Tf 490 {y} Td " + _pdf_string(f"{share:.1f}%").decode("latin1") + " Tj ET",
        ])
        y -= 30
    commands.extend([
        f"0.5 w 48 {y + 12} m 547 {y + 12} l S",
        f"BT /F1 11 Tf 48 {y - 10} Td " + _pdf_string("Los valores reflejan las compras agrupadas por estado.").decode("latin1") + " Tj ET",
    ])
    stream = "\n".join(commands).encode("latin1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(pdf)


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def build_sales_xlsx(report: Any, months: int) -> bytes:
    total = float(report.totalMonto)
    rows: list[list[Any]] = [
        ["Reporte de ventas totales"],
        [f"Periodo: últimos {months} meses", f"Generado: {date.today().isoformat()}"],
        ["Total del periodo (COP)", total],
        [],
        ["Estado", "Pedidos", "Monto (COP)", "Participación (%)"],
    ]
    for item in report.items:
        share = (float(item.monto) / total * 100) if total else 0
        rows.append([item.nombre, int(item.pedidos), float(item.monto), round(share, 2)])
    rows.append(["Total", sum(int(item.pedidos) for item in report.items), total, 100.0 if total else 0.0])

    xml_rows = []
    for row_number, row in enumerate(rows, start=1):
        cells = []
        for column_number, value in enumerate(row, start=1):
            reference = f"{_column_name(column_number)}{row_number}"
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
            else:
                text = escape(str(value))
                cells.append(f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>')
        xml_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Ventas totales" sheetId="1" r:id="rId1"/></sheets></workbook>')
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                     '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                 '</Relationships>')
    workbook_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                     '</Relationships>')
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()

import pdfkit
from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string


def generate_pdf_response(template_name, context, filename="document.pdf"):
    html_string = render_to_string(template_name, context)

    config = pdfkit.configuration(wkhtmltopdf=settings.WKHTMLTOPDF_PATH)
    options = {
        'page-size': 'A4',
        'margin-top': '12mm',
        'margin-right': '12mm',
        'margin-bottom': '12mm',
        'margin-left': '12mm',
        'encoding': 'UTF-8',
        'enable-local-file-access': None,
    }

    pdf_bytes = pdfkit.from_string(html_string, False, options=options, configuration=config)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

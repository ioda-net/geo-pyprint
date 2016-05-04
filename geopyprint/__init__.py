import os


from .mapprint import MapPrint
from pyramid.config import Configurator
from pyramid.response import FileResponse
from pyramid.renderers import JSONP
from pyramid.view import view_config


def main(global_config, **settings):
    config = Configurator(settings=settings)
    config.add_renderer('jsonp', JSONP(param_name='callback', indent=None, separators=(',', ':')))
    config.add_route('mapprint', '/print')

    config.scan()

    return config.make_wsgi_app()


@view_config(route_name='mapprint')
def mapprint(request):
    payload = request.json_body

    output_file_name = MapPrint(payload).print_pdf()

    response = FileResponse(
        output_file_name,
        request=request
    )
    response.headers['Content-Disposition'] = ('attachement; filename="{}"'
                                               .format(output_file_name + '.pdf'))
    response.headers['Content-Type'] = 'application/pdf'

    if os.path.exists(output_file_name):
        os.remove(output_file_name)

    return response
import asyncio
import functools
import requests
import subprocess


from PIL import Image
from pyramid.config import Configurator
from pyramid.response import FileResponse
from pyramid.renderers import JSONP
from pyramid.view import view_config
from secretary import Renderer
from tempfile import NamedTemporaryFile
from io import BytesIO

WMS_HEADERS = {'Referer': 'http://localhost'}


def main(global_config, **settings):
    config = Configurator(settings=settings)
    config.add_renderer('jsonp', JSONP(param_name='callback', indent=None, separators=(',', ':')))
    config.add_route('mapprint', '/print')

    config.scan()

    return config.make_wsgi_app()


@view_config(route_name='mapprint')
def mapprint(request):
    output = None

    payload = request.json_body

    loop = asyncio.new_event_loop()
    images = loop.run_until_complete(get_images(payload, loop))

    for resp in images:
        img = Image.open(resp.raw).convert('RGBA')
        if output is None:
            output = Image.new('RGBA', img.size)
        output = Image.alpha_composite(output, img)

    my_map = BytesIO()
    output.save(my_map, 'PNG')

    render = Renderer(media_path='.')
    result = render.render('template.odt', my_map=my_map)

    with NamedTemporaryFile(
            mode='wb+',
            prefix='geo-pyprint',
            delete=True) as output:
        output.write(result)
        output.flush()

        subprocess.call(['unoconv', '-f', 'pdf', '-o', output.name + '.pdf', output.name], timeout=None)

        response = FileResponse(
            output.name + '.pdf',
            request=request
        )
        response.headers['Content-Disposition'] = ('attachement; filename="{}"'
                                                   .format(output.name + '.pdf'))
        response.headers['Content-Type'] = 'application/pdf'

        return response


@asyncio.coroutine
def get_images(payload, loop):
    """
/ows/geojb?MAP_RESOLUTION=150&DPI=150&TRANSPARENT=true&LANG=fr&MAP.RESOLUTION=150&FORMAT=image%2Fpng&REQUEST=GetMap&SRS=EPSG%3A21781&BBOX=578059.45%2C217911.5%2C591940.5499999999%2C237088.5V&ERSION=1.1.1&STYLES=&SERVICE=WMS&WIDTH=1093&HEIGHT=1510&LAYERS=CADASTRE_A"
/ows/geojb?MAP_RESOLUTION=150&DPI=150&TRANSPARENT=true&LANG=fr&MAP.RESOLUTION=150&FORMAT=image%2Fpng&REQUEST=GetMap&SRS=EPSG%3A21781&BBOX=578059.45%2C217911.5%2C591940.5499999999%2C237088.5&VERSION=1.1.1&STYLES=&SERVICE=WMS&WIDTH=1093&HEIGHT=1510&LAYERS=CADASTRE_C"

BBOX=578059.45 217911.5 591940.5499999999 237088.5
WIDTH=1093
HEIGHT=1510
    """
    images = []

    map = payload['attributes']['map']
    epsg = map['projection']
    scale = map['scale']
    center = map['center']
    dpi = map['dpi']

    for layer in payload['attributes']['map']['layers']:
        if layer['type'].lower() == 'wms':
            base_url = layer['baseURL']

            bbox = get_bbox(center, scale, dpi)
            size = get_size(bbox, dpi, scale)

            params = {
                'VERSION': '1.1.1',
                'REQUEST': 'GetMap',
                'LAYERS': ','.join(layer['layers']),
                'SRS': epsg,
                'STYLES': '',
                'WIDTH': size[0],
                'HEIGHT': size[1],
                'BBOX': ','.join([str(nb) for nb in bbox]),
                'FORMAT': layer['imageFormat'],
            }



            custom_params = layer.get('customParams', {})
            transparent = False
            if 'TRANSPARENT' in custom_params:
                transparent = custom_params['TRANSPARENT']
                del custom_params['TRANSPARENT']

            params.update(custom_params)

            future_img = loop.run_in_executor(
                None,
                functools.partial(
                    requests.get,
                    base_url,
                    params=params,
                    headers=WMS_HEADERS,
                    stream=True
                )
            )

            images.append(future_img)

    return asyncio.gather(*images)


def get_size(bbox, dpi, scale):
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]

    width_inch = width * 39.37
    height_inch = height * 39.37

    return (int(width_inch * dpi / scale), int(height_inch * dpi / scale))


def get_bbox(center, scale, dpi):
    # https://github.com/mapfish/mapfish-print/blob/3c3db78c5f87baf4901e781f756778b9c4e713b0/core/src/main/java/org/mapfish/print/attribute/map/CenterScaleMapBounds.java#L41

    # In meters, from template
    paint_area_width = 210.01 * 10**-3
    paint_area_height = 297.0 * 10**-3

    geo_width = paint_area_width * scale
    geo_height = paint_area_height * scale

    x, y = center

    min_geo_x = x - (geo_width / 2.0)
    min_geo_y = y - (geo_height / 2.0)
    max_geo_x = min_geo_x + geo_width
    max_geo_y = min_geo_y + geo_height
    bbox = (min_geo_x, min_geo_y, max_geo_x, max_geo_y)

    return bbox

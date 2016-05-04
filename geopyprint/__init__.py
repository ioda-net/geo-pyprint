import asyncio
import functools
import requests
import subprocess


from pdfjinja import PdfJinja
from PIL import Image
from pyramid.config import Configurator
from pyramid.response import FileResponse
from pyramid.renderers import JSONP
from pyramid.view import view_config
from secretary import Renderer
from tempfile import NamedTemporaryFile
from io import BytesIO

WMS_HEADERS = {'Referer': 'http://localhost'}
LAYER_DPI = 25.4 / 0.28


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
    images = get_images(payload, loop)

    for img in images:
        if not isinstance(img, Image.Image):
            img = Image.open(BytesIO(img.content)).convert('RGBA')

        if img.size != (1240, 1743):
            img = img.resize((1240, 1743))

        if output is None:
            output = Image.new('RGBA', (1240, 1743))
        output = Image.alpha_composite(output, img)

    return create_pdf(request, output)


def create_pdf(request, output):
    return _create_pdf_libreoffice(request, output)
    #return _create_pdf_pdftk(request, output)


def _create_pdf_libreoffice(request, output):
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


def _create_pdf_pdftk(request, output):
    with NamedTemporaryFile(
        mode='wb+',
        prefix='geo-pypring',
        delete=False
    ) as output_img:
        output.save(output_img, 'PNG')
        output_img.flush()

        pdfjinja = PdfJinja('pdfjinja-template.pdf')
        pdfout = pdfjinja(dict(map=output_img.name))

        with NamedTemporaryFile(
            mode='wb+',
            prefix='geo-pypring',
            delete=False
        ) as output_pdf:
            pdfout.write(output_pdf)
            output_pdf.flush()

            response = FileResponse(
                output_pdf.name,
                request=request
            )
            response.headers['Content-Disposition'] = ('attachement; filename="{}"'
                                                       .format('pdfjinja.pdf'))
            response.headers['Content-Type'] = 'application/pdf'

            return response


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

    bbox = get_bbox(center, scale, dpi)
    size = get_size(bbox, dpi, scale)

    for layer in payload['attributes']['map']['layers']:
        if layer['type'].lower() == 'wms':
            base_url = layer['baseURL']

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

            params.update(custom_params)

            future_img = loop.run_in_executor(
                None,
                functools.partial(
                    requests.get,
                    base_url,
                    params=params,
                    headers=WMS_HEADERS
                )
            )

            images.append(future_img)
        elif layer['type'].lower() == 'wmts':
            matrix = layer['matrices'][0]
            for candidate_matrix in layer['matrices'][1:]:
                if abs(candidate_matrix['scaleDenominator'] - scale) < abs(matrix['scaleDenominator'] - scale):
                    matrix = candidate_matrix

            if layer['requestEncoding'].upper() == 'REST':
                size_on_screen = matrix['tileSize'][0], matrix['tileSize'][1]
                layer_resolution = matrix['scaleDenominator'] / (LAYER_DPI * 39.37)
                tile_size_in_world = (size_on_screen[0] * layer_resolution, size_on_screen[1] * layer_resolution)
                x_min, y_max = matrix['topLeftCorner'][0], matrix['topLeftCorner'][1]
                x_max, y_min = (x_min + tile_size_in_world[0], y_max - tile_size_in_world[1])
                col_min = 0
                col_max = 0
                row_min = 0
                row_max = 0
                col = 0
                row = 0
                wmts_bbox = [0, 0, 0, 0]
                while True:
                    if x_min <= bbox[0] and x_max > bbox[0]:
                        wmts_bbox[0] = x_min
                        col_min = col
                    if x_min <= bbox[2] and x_max > bbox[2]:
                        col_max = col
                        wmts_bbox[2] = x_max
                        break
                    col += 1
                    x_min = x_max
                    x_max += tile_size_in_world[0]

                while True:
                    if y_min < bbox[1] and y_max > bbox[1]:
                        row_max = row
                        wmts_bbox[1] = y_min
                        break
                    if y_min < bbox[3] and y_max > bbox[3]:
                        row_min = row
                        wmts_bbox[3] = y_max
                    row += 1
                    y_max = y_min
                    y_min -= tile_size_in_world[1]

                url = layer['baseURL'].replace('{TileMatrix}', matrix['identifier'])
                for dimension in layer['dimensions']:
                    url = url.replace('{' + dimension + '}', layer['dimensionParams'][dimension])

                width, height = size_on_screen
                combined_size = (width * (col_max - col_min + 1), height * (row_max - row_min + 1))
                combined_image = Image.new('RGBA', combined_size)
                for col in range(col_min, col_max + 1):
                    for row in range(row_min, row_max + 1):
                        resp = requests.get(url.replace('{TileRow}', str(row)).replace('{TileCol}', str(col)), headers=WMS_HEADERS)
                        if resp.status_code != 200:
                            continue

                        img = Image.open(BytesIO(resp.content)).convert('RGBA')
                        combined_image.paste(img, box=(width * (col - col_min), height * (row - row_min)))

                diff = bbox[0] - wmts_bbox[0], bbox[1] - wmts_bbox[1] - 800
                width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
                crop_box = int(diff[0] / layer_resolution), int(diff[1] / layer_resolution), int((diff[0] + width) / layer_resolution), int((diff[1] + height) / layer_resolution)

                wmts_cropped = combined_image.crop(box=crop_box)

                future = asyncio.Future(loop=loop)
                future.set_result(wmts_cropped)
                images.insert(0, future)

    return loop.run_until_complete(asyncio.gather(*images))


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
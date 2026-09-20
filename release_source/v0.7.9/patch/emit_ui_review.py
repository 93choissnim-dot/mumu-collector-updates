"""Send small synthetic-fixture UI previews through the existing CI log channel."""
import base64
import io
from pathlib import Path
from PIL import Image

for path in sorted((Path(__file__).parent/'exe_release').glob('review-*.png')):
    if path.name not in {'review-list.png','review-settings.png','review-compact.png','review-paused.png'}:continue
    with Image.open(path) as im:
        im.thumbnail((1220,820))
        stream=io.BytesIO()
        im.convert('RGB').quantize(colors=96).save(stream,format='PNG',optimize=True)
    data=base64.b64encode(stream.getvalue()).decode('ascii')
    for index in range(0,len(data),1200):
        print('UI_PREVIEW '+path.name+' '+str(index//1200)+' '+data[index:index+1200],flush=True)

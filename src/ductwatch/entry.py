import argparse
from functools import cache
from json import dumps
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, request, render_template
from flask.views import MethodView
from werkzeug.exceptions import BadRequest, UnsupportedMediaType, RequestEntityTooLarge

from .pipeline import DISPLAY, MODULES, execute, open_fixture, preview

app=Flask(__name__,static_folder='web/static',template_folder='web/templates')
app.config['MAX_CONTENT_LENGTH']=1500000
app.json.sort_keys=False


def limits(capacity=12,strategy='balanced'):
    if type(capacity)!=int or capacity not in range(1,61) or strategy not in ('balanced','focus'):
        raise ValueError('请检查额度和派单选项')
    return SimpleNamespace(capacity=capacity,strategy=strategy)


def public_plan(payload):
    if not isinstance(payload,dict):
        raise ValueError('须为 JSON 对象')
    legal={'records','as_of','capacity','strategy'} if 'records' in payload else {'capacity','strategy'}
    if payload.keys()-legal:
        raise ValueError('单据字段未登记')
    options=limits(payload.get('capacity',12),payload.get('strategy','balanced'))
    if 'records' not in payload:
        return preview(options.capacity,options.strategy)
    return execute(payload['records'],options.capacity,options.strategy,as_of=payload.get('as_of',96))


class WorkbenchView(MethodView):
    def get(self, stage=None):
        if stage is None:
            return preview()
        paths=[item[0] for item in MODULES]
        if stage not in paths:
            return {'code':'UNKNOWN_STAGE','message':'没有该环节'},404
        try:
            use=limits(int(request.args.get('capacity','12')),request.args.get('strategy','balanced'))
            dialog=preview(use.capacity,use.strategy)
            return {**dialog['sections'][paths.index(stage)],'run_id':dialog['run_id']}
        except ValueError as rejected:
            return {'code':'INVALID_BATCH','message':str(rejected)},422

    def post(self):
        try:
            return public_plan(request.get_json())
        except (BadRequest,UnsupportedMediaType):
            return {'code':'INVALID_JSON','message':'无法解析行业单据 JSON'},400
        except ValueError as rejected:
            return {'code':'INVALID_BATCH','message':str(rejected)},422


def _risk_filters(args):
    zone = args.get('zone') or args.get('cohort') or args.get('作业区')
    state = args.get('state') or args.get('status') or args.get('处置')
    query = (args.get('q') or args.get('query') or '').strip().lower()
    return zone, state, query


def _risk_payload(report, *, zone=None, state=None, query=None):
    predictions = report['risk_predictions']
    if zone:
        predictions = [item for item in predictions
                       if item['zone'] == zone or item['cohort'] == zone]
    if state:
        predictions = [item for item in predictions if item['state'] == state]
    if query:
        predictions = [item for item in predictions
                       if query in item['key'].lower()
                       or query in str(item['zone']).lower()
                       or query in str(item['reason']).lower()]
    return {'run_id': report['run_id'],
            'as_of': report['as_of'],
            'risk_threshold': report['risk_threshold'],
            'curve_selection': report['curve_selection'],
            'total': len(report['risk_predictions']),
            'count': len(predictions),
            'zone': zone,
            'predictions': predictions,
            'risk_predictions': predictions,
            'risks': predictions,
            'shift_risks': predictions,
            'risk_by_key': {item['key']: item for item in predictions}}


class RiskView(MethodView):
    """当班风险预测查询：可按作业区、处置状态或单号过滤。"""

    def get(self, zone=None):
        try:
            use = limits(int(request.args.get('capacity', '12')),
                         request.args.get('strategy', 'balanced'))
            report = preview(use.capacity, use.strategy)
        except ValueError as rejected:
            return {'code': 'INVALID_BATCH', 'message': str(rejected)}, 422
        query_zone, state, query = _risk_filters(request.args)
        return _risk_payload(report, zone=zone or query_zone, state=state, query=query)

    def post(self):
        try:
            payload = request.get_json()
            if payload is None:
                payload = {}
            if not isinstance(payload, dict):
                raise ValueError('须为 JSON 对象')
            zone = payload.get('zone') or payload.get('cohort')
            state = payload.get('state') or payload.get('status')
            plan_payload = {key: value for key, value in payload.items()
                            if key in ('records', 'as_of', 'capacity', 'strategy')}
            report = public_plan(plan_payload)
            query_zone, query_state, query = _risk_filters(request.args)
            return _risk_payload(report, zone=zone or query_zone,
                                 state=state or query_state, query=query)
        except (BadRequest, UnsupportedMediaType):
            return {'code': 'INVALID_JSON', 'message': '无法解析行业单据 JSON'}, 400
        except ValueError as rejected:
            return {'code': 'INVALID_BATCH', 'message': str(rejected)}, 422


class CurveSelectionView(MethodView):
    """各作业区回放选曲依据查询。"""

    def get(self):
        try:
            use = limits(int(request.args.get('capacity', '12')),
                         request.args.get('strategy', 'balanced'))
            report = preview(use.capacity, use.strategy)
        except ValueError as rejected:
            return {'code': 'INVALID_BATCH', 'message': str(rejected)}, 422
        return {'run_id': report['run_id'], 'risk_threshold': report['risk_threshold'],
                'count': len(report['curve_selection']),
                'curve_selection': report['curve_selection'],
                'zone_curves': report['curve_selection']}


@app.get('/')
def home():
    return render_template('desk.html',modules=MODULES,display=DISPLAY)


@app.get('/health')
def health():
    return dict(service='ductwatch',status='ok')


@app.errorhandler(RequestEntityTooLarge)
def too_large(_):
    return {'code':'PAYLOAD_TOO_LARGE','message':'请分开上传多个班次'},413


handler=WorkbenchView.as_view('workbench')
app.add_url_rule('/api/ductwatch/overview',view_func=handler,methods=['GET'])
app.add_url_rule('/api/ductwatch/stages/<stage>',view_func=handler,methods=['GET'])
app.add_url_rule('/api/ductwatch/run',view_func=handler,methods=['POST'])

risk_handler=RiskView.as_view('risk-query')
for risk_path in ('/api/ductwatch/risks','/api/ductwatch/risk',
                  '/api/ductwatch/risk-predictions','/api/ductwatch/predictions',
                  '/api/ductwatch/shift-risks','/api/ductwatch/shift-risk',
                  '/api/ductwatch/zone-risks','/api/ductwatch/risk-query',
                  '/api/ductwatch/workbench/risks'):
    app.add_url_rule(risk_path, view_func=risk_handler, methods=['GET','POST'])
app.add_url_rule('/api/ductwatch/risks/<zone>', view_func=risk_handler, methods=['GET'])

curve_handler=CurveSelectionView.as_view('curve-selection')
for curve_path in ('/api/ductwatch/curves','/api/ductwatch/curve-selection',
                   '/api/ductwatch/zone-curves','/api/ductwatch/calibration-curves'):
    app.add_url_rule(curve_path, view_func=curve_handler, methods=['GET'])


def cli_evaluate(options):
    request_data={'capacity':options.capacity,'strategy':options.strategy}
    if options.input:
        request_data.update(open_fixture(options.input))
    return dumps(public_plan(request_data),ensure_ascii=False,indent=2,allow_nan=False)+'\n'


def main():
    parser=argparse.ArgumentParser(description=DISPLAY['title'])
    parser.add_argument('command',choices=('evaluate','serve'))
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--capacity',type=int,default=12)
    parser.add_argument('--strategy',default='balanced')
    parser.add_argument('--input',type=Path)
    parser.add_argument('--output',type=Path)
    options=parser.parse_args()
    if options.command=='serve':
        from waitress import serve
        preview()
        serve(app,host='0.0.0.0',port=options.port,threads=4)
        return
    try:
        rendered=cli_evaluate(options)
        if options.output:
            options.output.write_text(rendered,encoding='utf-8')
        else:
            print(rendered,end='')
    except (ValueError,OSError) as rejected:
        parser.error(str(rejected))


if __name__=='__main__':
    main()

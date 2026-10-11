"""Date-scoped database views and edits; other observation periods are retained."""
import copy
from app import monitoring as m
from monitoring_daily.services.observation_date import normalize_observation_date

def raw_for_date(project, key, date):
    rows = project.payload.get('measurements', {}).get(key, [])
    if key.startswith('inclinometer:'):
        result = [{'深度': row.get('深度'), date: next((v for k, v in row.items() if normalize_observation_date(k) == date), None)} for row in rows] if date else []
        return result, ['深度', date] if date else ['深度']
    result = [copy.deepcopy(row) for row in rows if date and normalize_observation_date(row.get('时间')) == date]
    columns = list(dict.fromkeys(c for row in result for c in row))
    return result, columns

def replace_date_rows(project, key, date, edited):
    date = normalize_observation_date(date)
    reader = m.MonitoringReader(m.service_for(project))
    if not date or date not in reader.list_dates(key):
        raise ValueError('请选择当前测项中存在的监测日期')
    original = copy.deepcopy(project.payload.get('measurements', {}).get(key, []))
    if key.startswith('inclinometer:'):
        # Keep depth identities fixed: editing one period must not move another period's readings.
        def depth(row):
            return float(row.get('深度'))
        indexed = {depth(row): row for row in original}
        if len(edited) != len(original) or {depth(row) for row in edited} != set(indexed):
            raise ValueError('数据库编辑不能增删或修改深度，请在数据录入中操作')
        for row in edited:
            if set(row) != {'深度', date}:
                raise ValueError('只能编辑所选日期的读数')
            target = indexed[depth(row)]
            for column in list(target):
                if normalize_observation_date(column) == date:
                    del target[column]
            target[date] = row[date]
        return original
    if any(normalize_observation_date(row.get('时间')) != date for row in edited):
        raise ValueError('只能编辑所选日期的数据，不能更改到其他日期')
    retained = [row for row in original if normalize_observation_date(row.get('时间')) != date]
    return retained + m.normalize_rows(key, edited)

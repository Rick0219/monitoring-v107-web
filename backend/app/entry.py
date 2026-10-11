"""Single-period web entry using the desktop parameter and calculation services."""
import copy
import math
from app import monitoring as m
from monitoring_daily.services.project_service import ProjectService
from monitoring_daily.services.axial_force import AXIAL_PARAMETER_COLUMNS
from monitoring_daily.services.tilt import TILT_PARAMETER_COLUMNS
from monitoring_daily.services.water_level import WATER_PARAMETER_COLUMNS
from monitoring_daily.domain.monitoring import EXCEL_SHEETS


class EntryService(m.MemoryProjectService):
    _rows_with_water_parameters = ProjectService._rows_with_water_parameters

    @staticmethod
    def _synchronize_beautified_candidate(candidate, affected_dates):
        # The web app operates on raw observations, without desktop beautification.
        return candidate

    @classmethod
    def _recalculate_linked_tilt_data_for_payload(cls, payload, data_name):
        # Preserve legacy imported independent results until linkage is configured.
        if 'tilt:' + data_name in payload.get('tilt_parameters', {}):
            ProjectService._recalculate_linked_tilt_data_for_payload(payload, data_name)


def service_for(project):
    source = m.service_for(project)
    service = EntryService()
    service.current_project, service._payload = source.current_project, source._payload
    return service


def context(key, date):
    monitor, _, name = key.partition(':')
    m.validate_rows(key, [])
    if monitor in {'axial', 'tilt'} and not name:
        if monitor == 'tilt':
            raise ValueError('倾斜必须选择对应水准测项')
    observed = m.normalize_observation_date(date)
    if not observed:
        raise ValueError('监测日期无效，请选择日期')
    return monitor, name or None, observed


def parameter_rows(service, monitor, name):
    if monitor == 'axial':
        return service.list_axial_parameters(name), AXIAL_PARAMETER_COLUMNS
    if monitor == 'water':
        return service.list_water_parameters(), WATER_PARAMETER_COLUMNS
    if monitor == 'tilt':
        return service.list_tilt_parameters(name), TILT_PARAMETER_COLUMNS
    if monitor == 'inclinometer':
        rows = service._payload.get('measurements', {}).get('inclinometer_points', [])
        return [r for r in rows if str(r.get('点号', '')) == name], ['点号', '起始位置', '步长', '深度']
    return [], []


def profile_number(value):
    number = float(str(value).replace('米', '').replace('m', '').replace('M', '').strip())
    if not math.isfinite(number) or number <= 0:
        raise ValueError('步长和深度必须是大于 0 的有限数值')
    return number


def depth_rows(profile):
    step, depth = profile_number(profile['步长']), profile_number(profile['深度'])
    count = int((depth + 1e-9) / step)
    if not 1 <= count <= 20000:
        raise ValueError('生成深度行数必须为 1 至 20000 行，请检查步长和深度')
    return [{'深度': round(step * index, 6), '测值': ''} for index in range(1, count + 1)]


def read_entry(project, key, date):
    monitor, name, observed = context(key, date)
    service = service_for(project)
    parameters, parameter_columns = parameter_rows(service, monitor, name)
    if monitor == 'tilt':
        rows = service.calculate_tilt_rows(name, observed)
    else:
        rows = service.load_measurements(monitor, name, observed_date=observed)
    if not rows and monitor == 'water':
        rows = [{'序号': i, '时间': observed, **p, '水位读数（m）': '', '备注': ''}
                for i, p in enumerate(parameters, 1)]
    if monitor == 'inclinometer' and parameters:
        values = {float(row['深度']): row.get('测值', '') for row in rows}
        rows = [{**row, '测值': values.get(float(row['深度']), '')} for row in depth_rows(parameters[0])]
    columns = m.TABLE_HEADERS[monitor]
    readonly = ['序号', '时间']
    if monitor == 'axial':
        readonly += ['点号', '编号', '轴力（kN）']
    elif monitor == 'water':
        readonly += ['点位', '管口高程（m）']
    elif monitor == 'tilt':
        readonly = columns
    copy_rows, seen = [], set()
    if monitor in {'level', 'horizontal'}:
        for row in service.load_measurement_set(key):
            point = str(row.get('点号', ''))
            if point and point not in seen:
                seen.add(point)
                copy_rows.append({'序号': len(copy_rows) + 1, '时间': observed, '点号': point})
    return {'revision': project.revision, 'measurement_key': key, 'date': observed,
            'rows': rows, 'columns': columns, 'readonly': readonly,
            'parameters': parameters, 'parameter_columns': parameter_columns,
            'level_points': service.list_level_points(name) if monitor == 'tilt' else [],
            'copy_rows': copy_rows, 'excel_sheet': EXCEL_SHEETS.get(monitor, ''),
            'dates': m.MonitoringReader(service).list_dates(key) if key in service._payload.get('measurements', {}) else []}


def prepare_rows(service, key, date, rows):
    monitor, name, observed = context(key, date)
    if monitor == 'tilt':
        return service.calculate_tilt_rows(name, observed)
    rows = m.normalize_rows(key, rows)
    columns = m.TABLE_HEADERS[monitor]
    normalized = [{column: row.get(column, '') for column in columns} for row in rows]
    for i, row in enumerate(normalized, 1):
        if '时间' in columns:
            row['时间'] = observed
        if '序号' in columns:
            row['序号'] = i
    if monitor == 'axial':
        parameters = {str(p['编号']): p for p in service.list_axial_parameters(name)}
        for row in normalized:
            param = parameters.get(str(row.get('编号', '')))
            if not param or str(param['点号']) != str(row.get('点号', '')):
                raise ValueError(f"点号 {row.get('点号')}、编号 {row.get('编号')} 未配置，请先设置轴力参数")
        normalized = service.calculate_axial_rows(normalized, name)
    elif monitor == 'water':
        available = {str(p['点位']) for p in service.list_water_parameters()}
        if any(str(r.get('点位')) not in available for r in normalized):
            raise ValueError('请先在水位参数中配置点位和管口高程')
        normalized = service._rows_with_water_parameters(normalized)
    check = normalized
    if monitor == 'inclinometer':
        check = [{'深度': r.get('深度'), observed: r.get('测值')} for r in normalized]
        depths = [float(r['深度']) for r in check if str(r.get('深度', '')).strip()]
        if len(set(depths)) != len(depths):
            raise ValueError('深度不能重复')
    m.validate_rows(key, check)
    return normalized


def save_entry(project, key, date, rows):
    monitor, name, observed = context(key, date)
    service = service_for(project)
    normalized = prepare_rows(service, key, observed, rows)
    if monitor == 'tilt':
        service._recalculate_linked_tilt_data(name)
    elif monitor == 'inclinometer' and not normalized:
        # Clearing one period must never delete other periods of the hole.
        stored = service._payload.setdefault('measurements', {}).get(key, [])
        for row in stored:
            row.pop(observed, None)
        if not any(any(m.normalize_observation_date(column) for column in row) for row in stored):
            service._payload['measurements'].pop(key, None)
    else:
        service.save_measurements(monitor, normalized, name, observed_date=observed)
    stored = service._payload.get('measurements', {}).get(key, [])
    m.validate_rows(key, stored)
    return service._payload


def save_parameters(project, key, rows):
    monitor, name, _ = context(key, '2000-01-01')
    service = service_for(project)
    _, columns = parameter_rows(service, monitor, name)
    if not columns:
        raise ValueError('当前监测类型没有参数表')
    for i, row in enumerate(rows, 1):
        for column, value in row.items():
            if column not in columns or isinstance(value, (dict, list, bool)):
                raise ValueError(f'第 {i} 行参数字段无效：{column}')
            if column not in {'点号', '编号', '点位', '点号1', '点号2', '传感器类型', '起始位置'} and value not in ('', None, '/'):
                if not math.isfinite(float(str(value).replace('m', '').replace('米', ''))):
                    raise ValueError(f'第 {i} 行 {column} 必须是有限数值')
    if monitor == 'axial':
        service.save_axial_parameters(rows, name)
    elif monitor == 'tilt':
        service.save_tilt_parameters(rows, name)
        if not rows:
            service._payload.setdefault('measurements', {}).pop(key, None)
    elif monitor == 'water':
        service.save_water_parameters(rows)
        # Imported named water sets also share the desktop water parameter library.
        for stored_key, stored in service._payload.get('measurements', {}).items():
            if stored_key.startswith('water:'):
                service._payload['measurements'][stored_key] = service._rows_with_water_parameters(stored)
    else:
        if len(rows) != 1 or str(rows[0].get('点号', '')) != name:
            raise ValueError('孔号参数必须与当前孔号一致')
        depth_rows(rows[0])
        if rows[0].get('起始位置') not in {'孔底', '孔口'}:
            raise ValueError('起始位置请选择孔底或孔口')
        profiles = service._payload.setdefault('measurements', {}).setdefault('inclinometer_points', [])
        service._payload['measurements']['inclinometer_points'] = [r for r in profiles if r.get('点号') != name] + copy.deepcopy(rows)
    return service._payload

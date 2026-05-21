# -*- coding: utf-8 -*-
"""
闲鱼景点讲解订单管理系统
Flask + SQLite 后端
"""

import os
import sqlite3
import csv
import io
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orders.db')


# ==================== 数据库工具 ====================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS agencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            contact TEXT,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            specialty TEXT,
            agency_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (agency_id) REFERENCES agencies(id)
        );

        CREATE TABLE IF NOT EXISTS scenic_spots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            city TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT UNIQUE,
            scenic_spot TEXT NOT NULL,
            visit_date DATE NOT NULL,
            customer_name TEXT,
            customer_phone TEXT,
            guest_count INTEGER DEFAULT 1,
            unit_price REAL DEFAULT 0,
            total_price REAL DEFAULT 0,
            agency_id INTEGER,
            teacher_id INTEGER,
            status TEXT DEFAULT '待确认',
            refund_amount REAL DEFAULT 0,
            refund_reason TEXT,
            notes TEXT,
            xianyu_order_no TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (agency_id) REFERENCES agencies(id),
            FOREIGN KEY (teacher_id) REFERENCES teachers(id)
        );

        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_orders_visit_date ON orders(visit_date);
        CREATE INDEX IF NOT EXISTS idx_orders_agency ON orders(agency_id);
        CREATE INDEX IF NOT EXISTS idx_orders_teacher ON orders(teacher_id);
    ''')
    conn.commit()
    conn.close()


def dict_from_row(row):
    if row is None:
        return None
    return dict(row)


# ==================== 订单API ====================

def generate_order_no():
    """生成订单号: YYYYMMDD-序号"""
    today = datetime.now().strftime('%Y%m%d')
    conn = get_db()
    cur = conn.execute(
        "SELECT COUNT(*) as cnt FROM orders WHERE order_no LIKE ?",
        (f'{today}-%',)
    )
    cnt = cur.fetchone()['cnt']
    conn.close()
    return f'{today}-{cnt + 1:03d}'


@app.route('/api/orders', methods=['GET'])
def get_orders():
    conn = get_db()
    status = request.args.get('status', '')
    month = request.args.get('month', '')
    agency_id = request.args.get('agency_id', '')
    keyword = request.args.get('keyword', '')

    query = '''
        SELECT o.*, a.name as agency_name, t.name as teacher_name
        FROM orders o
        LEFT JOIN agencies a ON o.agency_id = a.id
        LEFT JOIN teachers t ON o.teacher_id = t.id
        WHERE 1=1
    '''
    params = []

    if status:
        query += ' AND o.status = ?'
        params.append(status)
    if month:
        query += ' AND strftime("%Y-%m", o.visit_date) = ?'
        params.append(month)
    if agency_id:
        query += ' AND o.agency_id = ?'
        params.append(int(agency_id))
    if keyword:
        query += ' AND (o.customer_name LIKE ? OR o.order_no LIKE ? OR o.scenic_spot LIKE ? OR o.xianyu_order_no LIKE ?)'
        kw = f'%{keyword}%'
        params.extend([kw, kw, kw, kw])

    query += ' ORDER BY o.visit_date DESC, o.created_at DESC'

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([dict_from_row(r) for r in rows])


@app.route('/api/orders/<int:order_id>', methods=['GET'])
def get_order(order_id):
    conn = get_db()
    row = conn.execute('''
        SELECT o.*, a.name as agency_name, t.name as teacher_name
        FROM orders o
        LEFT JOIN agencies a ON o.agency_id = a.id
        LEFT JOIN teachers t ON o.teacher_id = t.id
        WHERE o.id = ?
    ''', (order_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': '订单不存在'}), 404
    return jsonify(dict_from_row(row))


@app.route('/api/orders', methods=['POST'])
def create_order():
    data = request.json
    conn = get_db()

    order_no = data.get('order_no') or generate_order_no()
    total_price = (data.get('guest_count', 1) * data.get('unit_price', 0))

    try:
        cur = conn.execute('''
            INSERT INTO orders (order_no, scenic_spot, visit_date, customer_name, customer_phone,
                guest_count, unit_price, total_price, agency_id, teacher_id, status, notes, xianyu_order_no)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            order_no,
            data['scenic_spot'],
            data['visit_date'],
            data.get('customer_name', ''),
            data.get('customer_phone', ''),
            data.get('guest_count', 1),
            data.get('unit_price', 0),
            total_price,
            data.get('agency_id'),
            data.get('teacher_id'),
            data.get('status', '待确认'),
            data.get('notes', ''),
            data.get('xianyu_order_no', '')
        ))
        conn.commit()
        order_id = cur.lastrowid

        row = conn.execute('''
            SELECT o.*, a.name as agency_name, t.name as teacher_name
            FROM orders o
            LEFT JOIN agencies a ON o.agency_id = a.id
            LEFT JOIN teachers t ON o.teacher_id = t.id
            WHERE o.id = ?
        ''', (order_id,)).fetchone()
        conn.close()
        return jsonify(dict_from_row(row)), 201
    except sqlite3.IntegrityError as e:
        conn.close()
        return jsonify({'error': f'订单号重复: {str(e)}'}), 400


@app.route('/api/orders/<int:order_id>', methods=['PUT'])
def update_order(order_id):
    data = request.json
    conn = get_db()

    existing = conn.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({'error': '订单不存在'}), 404

    fields = []
    params = []

    for key in ['scenic_spot', 'visit_date', 'customer_name', 'customer_phone',
                'guest_count', 'unit_price', 'agency_id', 'teacher_id',
                'status', 'refund_amount', 'refund_reason', 'notes', 'xianyu_order_no']:
        if key in data:
            fields.append(f'{key} = ?')
            params.append(data[key])

    # 自动计算总价
    if 'guest_count' in data or 'unit_price' in data:
        gc = data.get('guest_count', existing['guest_count'])
        up = data.get('unit_price', existing['unit_price'])
        fields.append('total_price = ?')
        params.append(gc * up)

    fields.append('updated_at = CURRENT_TIMESTAMP')
    params.append(order_id)

    conn.execute(f'UPDATE orders SET {", ".join(fields)} WHERE id = ?', params)
    conn.commit()

    row = conn.execute('''
        SELECT o.*, a.name as agency_name, t.name as teacher_name
        FROM orders o
        LEFT JOIN agencies a ON o.agency_id = a.id
        LEFT JOIN teachers t ON o.teacher_id = t.id
        WHERE o.id = ?
    ''', (order_id,)).fetchone()
    conn.close()
    return jsonify(dict_from_row(row))


@app.route('/api/orders/<int:order_id>', methods=['DELETE'])
def delete_order(order_id):
    conn = get_db()
    conn.execute('DELETE FROM orders WHERE id = ?', (order_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/orders/<int:order_id>/cancel', methods=['POST'])
def cancel_order(order_id):
    """取消/退款订单"""
    data = request.json or {}
    conn = get_db()
    conn.execute('''
        UPDATE orders SET status = ?, refund_amount = ?, refund_reason = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (
        data.get('status', '已退款'),
        data.get('refund_amount', 0),
        data.get('refund_reason', ''),
        order_id
    ))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ==================== 旅行社API ====================

@app.route('/api/agencies', methods=['GET'])
def get_agencies():
    conn = get_db()
    rows = conn.execute('SELECT * FROM agencies ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict_from_row(r) for r in rows])


@app.route('/api/agencies', methods=['POST'])
def create_agency():
    data = request.json
    conn = get_db()
    try:
        cur = conn.execute(
            'INSERT INTO agencies (name, contact, phone) VALUES (?, ?, ?)',
            (data['name'], data.get('contact', ''), data.get('phone', ''))
        )
        conn.commit()
        aid = cur.lastrowid
        conn.close()
        return jsonify({'id': aid, 'name': data['name']}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': '旅行社名称已存在'}), 400


@app.route('/api/agencies/<int:agency_id>', methods=['PUT'])
def update_agency(agency_id):
    data = request.json
    conn = get_db()
    conn.execute(
        'UPDATE agencies SET name=?, contact=?, phone=? WHERE id=?',
        (data['name'], data.get('contact', ''), data.get('phone', ''), agency_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/agencies/<int:agency_id>', methods=['DELETE'])
def delete_agency(agency_id):
    conn = get_db()
    conn.execute('DELETE FROM agencies WHERE id = ?', (agency_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ==================== 讲解老师API ====================

@app.route('/api/teachers', methods=['GET'])
def get_teachers():
    conn = get_db()
    agency_id = request.args.get('agency_id', '')
    query = '''
        SELECT t.*, a.name as agency_name
        FROM teachers t
        LEFT JOIN agencies a ON t.agency_id = a.id
    '''
    params = []
    if agency_id:
        query += ' WHERE t.agency_id = ?'
        params.append(int(agency_id))
    query += ' ORDER BY t.name'
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([dict_from_row(r) for r in rows])


@app.route('/api/teachers', methods=['POST'])
def create_teacher():
    data = request.json
    conn = get_db()
    cur = conn.execute(
        'INSERT INTO teachers (name, phone, specialty, agency_id) VALUES (?, ?, ?, ?)',
        (data['name'], data.get('phone', ''), data.get('specialty', ''), data.get('agency_id'))
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return jsonify({'id': tid, 'name': data['name']}), 201


@app.route('/api/teachers/<int:teacher_id>', methods=['PUT'])
def update_teacher(teacher_id):
    data = request.json
    conn = get_db()
    conn.execute(
        'UPDATE teachers SET name=?, phone=?, specialty=?, agency_id=? WHERE id=?',
        (data['name'], data.get('phone', ''), data.get('specialty', ''), data.get('agency_id'), teacher_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/teachers/<int:teacher_id>', methods=['DELETE'])
def delete_teacher(teacher_id):
    conn = get_db()
    conn.execute('DELETE FROM teachers WHERE id = ?', (teacher_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ==================== 景点API ====================

@app.route('/api/scenic-spots', methods=['GET'])
def get_scenic_spots():
    conn = get_db()
    rows = conn.execute('SELECT * FROM scenic_spots ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict_from_row(r) for r in rows])


@app.route('/api/scenic-spots', methods=['POST'])
def create_scenic_spot():
    data = request.json
    conn = get_db()
    try:
        cur = conn.execute(
            'INSERT INTO scenic_spots (name, city) VALUES (?, ?)',
            (data['name'], data.get('city', ''))
        )
        conn.commit()
        sid = cur.lastrowid
        conn.close()
        return jsonify({'id': sid, 'name': data['name']}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': '景点名称已存在'}), 400


@app.route('/api/scenic-spots/<int:spot_id>', methods=['PUT'])
def update_scenic_spot(spot_id):
    data = request.json
    conn = get_db()
    conn.execute(
        'UPDATE scenic_spots SET name=?, city=? WHERE id=?',
        (data['name'], data.get('city', ''), spot_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/scenic-spots/<int:spot_id>', methods=['DELETE'])
def delete_scenic_spot(spot_id):
    conn = get_db()
    conn.execute('DELETE FROM scenic_spots WHERE id = ?', (spot_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ==================== 结算报表API ====================

@app.route('/api/settlement', methods=['GET'])
def get_settlement():
    month = request.args.get('month', datetime.now().strftime('%Y-%m'))

    conn = get_db()

    # 总览统计
    overview = conn.execute('''
        SELECT
            COUNT(*) as total_orders,
            SUM(CASE WHEN status = '已完成' THEN 1 ELSE 0 END) as completed_count,
            SUM(CASE WHEN status = '已完成' THEN total_price ELSE 0 END) as completed_amount,
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN 1 ELSE 0 END) as refunded_count,
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN refund_amount ELSE 0 END) as refunded_amount
        FROM orders
        WHERE strftime('%Y-%m', visit_date) = ?
    ''', (month,)).fetchone()

    # 按旅行社汇总
    by_agency = conn.execute('''
        SELECT
            a.id as agency_id,
            a.name as agency_name,
            COUNT(*) as total_orders,
            SUM(CASE WHEN status = '已完成' THEN 1 ELSE 0 END) as completed_count,
            SUM(CASE WHEN status = '已完成' THEN total_price ELSE 0 END) as completed_amount,
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN 1 ELSE 0 END) as refunded_count,
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN refund_amount ELSE 0 END) as refunded_amount,
            SUM(CASE WHEN status = '已完成' THEN total_price ELSE 0 END) -
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN refund_amount ELSE 0 END) as net_amount
        FROM orders o
        LEFT JOIN agencies a ON o.agency_id = a.id
        WHERE strftime('%Y-%m', o.visit_date) = ?
        GROUP BY o.agency_id
        ORDER BY a.name
    ''', (month,)).fetchall()

    # 按讲解老师汇总
    by_teacher = conn.execute('''
        SELECT
            t.id as teacher_id,
            t.name as teacher_name,
            a.name as agency_name,
            COUNT(*) as total_orders,
            SUM(CASE WHEN status = '已完成' THEN 1 ELSE 0 END) as completed_count,
            SUM(CASE WHEN status = '已完成' THEN total_price ELSE 0 END) as completed_amount,
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN 1 ELSE 0 END) as refunded_count,
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN refund_amount ELSE 0 END) as refunded_amount,
            SUM(CASE WHEN status = '已完成' THEN total_price ELSE 0 END) -
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN refund_amount ELSE 0 END) as net_amount
        FROM orders o
        LEFT JOIN teachers t ON o.teacher_id = t.id
        LEFT JOIN agencies a ON t.agency_id = a.id
        WHERE strftime('%Y-%m', o.visit_date) = ?
        GROUP BY o.teacher_id
        ORDER BY a.name, t.name
    ''', (month,)).fetchall()

    # 本月所有订单明细
    orders = conn.execute('''
        SELECT o.*, a.name as agency_name, t.name as teacher_name
        FROM orders o
        LEFT JOIN agencies a ON o.agency_id = a.id
        LEFT JOIN teachers t ON o.teacher_id = t.id
        WHERE strftime('%Y-%m', o.visit_date) = ?
        ORDER BY o.visit_date, o.created_at
    ''', (month,)).fetchall()

    conn.close()

    return jsonify({
        'month': month,
        'overview': dict_from_row(overview),
        'by_agency': [dict_from_row(r) for r in by_agency],
        'by_teacher': [dict_from_row(r) for r in by_teacher],
        'orders': [dict_from_row(r) for r in orders]
    })


# ==================== Excel导出 ====================

@app.route('/api/export/settlement', methods=['GET'])
def export_settlement():
    month = request.args.get('month', datetime.now().strftime('%Y-%m'))

    conn = get_db()

    # 获取结算数据
    overview = conn.execute('''
        SELECT
            COUNT(*) as total_orders,
            SUM(CASE WHEN status = '已完成' THEN 1 ELSE 0 END) as completed_count,
            SUM(CASE WHEN status = '已完成' THEN total_price ELSE 0 END) as completed_amount,
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN 1 ELSE 0 END) as refunded_count,
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN refund_amount ELSE 0 END) as refunded_amount
        FROM orders
        WHERE strftime('%Y-%m', visit_date) = ?
    ''', (month,)).fetchone()

    by_agency = conn.execute('''
        SELECT
            a.name as agency_name,
            COUNT(*) as total_orders,
            SUM(CASE WHEN status = '已完成' THEN 1 ELSE 0 END) as completed_count,
            SUM(CASE WHEN status = '已完成' THEN total_price ELSE 0 END) as completed_amount,
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN 1 ELSE 0 END) as refunded_count,
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN refund_amount ELSE 0 END) as refunded_amount,
            SUM(CASE WHEN status = '已完成' THEN total_price ELSE 0 END) -
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN refund_amount ELSE 0 END) as net_amount
        FROM orders o
        LEFT JOIN agencies a ON o.agency_id = a.id
        WHERE strftime('%Y-%m', o.visit_date) = ?
        GROUP BY o.agency_id
        ORDER BY a.name
    ''', (month,)).fetchall()

    orders = conn.execute('''
        SELECT o.order_no, o.scenic_spot, o.visit_date, o.customer_name, o.customer_phone,
               o.guest_count, o.unit_price, o.total_price, o.status, o.refund_amount, o.refund_reason,
               o.xianyu_order_no,
               a.name as agency_name, t.name as teacher_name
        FROM orders o
        LEFT JOIN agencies a ON o.agency_id = a.id
        LEFT JOIN teachers t ON o.teacher_id = t.id
        WHERE strftime('%Y-%m', o.visit_date) = ?
        ORDER BY o.visit_date, o.created_at
    ''', (month,)).fetchall()

    conn.close()

    # 生成CSV
    output = io.StringIO()
    output.write('\ufeff')  # BOM for Excel UTF-8
    writer = csv.writer(output)

    # 总览
    ov = dict_from_row(overview)
    writer.writerow([f'{month} 月度结算报表'])
    writer.writerow([])
    writer.writerow(['总览'])
    writer.writerow(['总订单数', '已完成数', '已完成金额', '退款数', '退款金额', '净收入'])
    writer.writerow([
        ov['total_orders'] or 0,
        ov['completed_count'] or 0,
        f"¥{ov['completed_amount'] or 0:.2f}",
        ov['refunded_count'] or 0,
        f"¥{ov['refunded_amount'] or 0:.2f}",
        f"¥{(ov['completed_amount'] or 0) - (ov['refunded_amount'] or 0):.2f}"
    ])

    # 按旅行社
    writer.writerow([])
    writer.writerow(['按旅行社汇总'])
    writer.writerow(['旅行社', '总订单', '已完成', '已完成金额', '退款数', '退款金额', '净收入'])
    for a in by_agency:
        writer.writerow([
            a['agency_name'] or '未分配',
            a['total_orders'],
            a['completed_count'] or 0,
            f"¥{a['completed_amount'] or 0:.2f}",
            a['refunded_count'] or 0,
            f"¥{a['refunded_amount'] or 0:.2f}",
            f"¥{a['net_amount'] or 0:.2f}"
        ])

    # 订单明细
    writer.writerow([])
    writer.writerow(['订单明细'])
    writer.writerow([
        '订单号', '景点', '游览日期', '客户姓名', '客户电话', '人数', '单价', '总价',
        '状态', '退款金额', '退款原因', '闲鱼订单号', '旅行社', '讲解老师'
    ])
    for o in orders:
        writer.writerow([
            o['order_no'], o['scenic_spot'], o['visit_date'],
            o['customer_name'], o['customer_phone'],
            o['guest_count'], f"¥{o['unit_price']:.2f}", f"¥{o['total_price']:.2f}",
            o['status'], f"¥{o['refund_amount']:.2f}" if o['refund_amount'] else '',
            o['refund_reason'] or '', o['xianyu_order_no'] or '',
            o['agency_name'] or '', o['teacher_name'] or ''
        ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'结算报表_{month}.csv'
    )


# ==================== 仪表盘统计 ====================

@app.route('/api/dashboard', methods=['GET'])
def get_dashboard():
    conn = get_db()
    this_month = datetime.now().strftime('%Y-%m')
    last_month = (datetime.now().replace(day=1) - timedelta(days=1)).strftime('%Y-%m')

    # 本月统计
    this = conn.execute('''
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = '已完成' THEN total_price ELSE 0 END) as income,
            SUM(CASE WHEN status IN ('已取消', '已退款') THEN refund_amount ELSE 0 END) as refund,
            SUM(CASE WHEN status = '待确认' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN status IN ('已确认', '已派发') THEN 1 ELSE 0 END) as processing
        FROM orders
        WHERE strftime('%Y-%m', visit_date) = ?
    ''', (this_month,)).fetchone()

    # 上月统计
    last = conn.execute('''
        SELECT
            SUM(CASE WHEN status = '已完成' THEN total_price ELSE 0 END) as income
        FROM orders
        WHERE strftime('%Y-%m', visit_date) = ?
    ''', (last_month,)).fetchone()

    # 待处理订单
    pending_orders = conn.execute('''
        SELECT o.*, a.name as agency_name, t.name as teacher_name
        FROM orders o
        LEFT JOIN agencies a ON o.agency_id = a.id
        LEFT JOIN teachers t ON o.teacher_id = t.id
        WHERE o.status IN ('待确认', '已确认', '已派发')
        ORDER BY o.visit_date
        LIMIT 10
    ''').fetchall()

    conn.close()

    return jsonify({
        'this_month': {
            'month': this_month,
            'total': dict_from_row(this)['total'] or 0,
            'income': dict_from_row(this)['income'] or 0,
            'refund': dict_from_row(this)['refund'] or 0,
            'net': (dict_from_row(this)['income'] or 0) - (dict_from_row(this)['refund'] or 0),
            'pending': dict_from_row(this)['pending'] or 0,
            'processing': dict_from_row(this)['processing'] or 0,
        },
        'last_month_income': dict_from_row(last)['income'] or 0,
        'pending_orders': [dict_from_row(r) for r in pending_orders]
    })


# ==================== 页面路由 ====================

@app.route('/')
def index():
    return render_template('index.html')


# ==================== 启动 ====================

if __name__ == '__main__':
    init_db()
    print('=' * 50)
    print('  闲鱼景点讲解订单管理系统')
    print(f'  数据文件: {DB_PATH}')
    print('  访问地址: http://127.0.0.1:5678')
    print('=' * 50)
    app.run(host='127.0.0.1', port=5678, debug=True)

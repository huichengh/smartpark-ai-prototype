"""演示数据生成主程序。

运行：python -m app.seed.seed_data
幂等：每次运行先清空业务数据表再重建。

设计原则：
  1. 所有数据由数据库真实写入，前端不得硬编码；
  2. 所有记录 is_demo=True，remark 统一标注「演示数据」；
  3. 数值之间保持逻辑自洽（合同面积=空间面积、账单金额=租金单价×面积等）；
  4. 保留足够的偏差与异常，使 AI 分析与预警有真实可解释的输入。
"""
from __future__ import annotations

import datetime as dt
import random

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models import (
    AccessRecord, Activity, AIConversation, AIMessage, AIRecommendation,
    ApprovalRequest, ApprovalStep, AuditLog, Bill, Building, Channel, Contract,
    Device, DeviceInspection, EnergyRecord, Enterprise, EnterpriseContact,
    EnterpriseTag, Epic, Feature, Floor, LeasingActivity, LeasingFollowup,
    LeasingLead, MeetingRoomBooking, Milestone, Notification, Organization,
    ParkingSpace, Payment, Permission, Policy, PolicyMatch, Project,
    ProjectChange, ProjectCost, ProjectIssue, ProjectPhase, ProjectRisk,
    ReportRecord, Role, RolePermission, SafetyHazard, SafetyIncident,
    ServiceRequest, Space, Sprint, SprintTask, TaskDependency, User,
    UserParkScope, UserRole, UserStory, Vehicle, Visitor, WbsItem, WorkOrder,
    Park, ParkTemplate,
)
from app.seed.reference import (
    ACTIONS, INDUSTRIES, MODULES_FOR_PERM, PARK_TEMPLATES, ROLE_PERM_MATRIX,
    ROLES, cn_name, credit_code, gen_company_name, phone,
)

random.seed(20260917)
TODAY = dt.date.today()
NOW = dt.datetime.now()
LABEL = "演示数据"


def d(offset: int) -> dt.date:
    return TODAY + dt.timedelta(days=offset)


def tm(offset: int = 0, hour: int = 9, minute: int = 0) -> dt.datetime:
    return dt.datetime.combine(d(offset), dt.time(hour, minute))


def pick(seq, i):
    return seq[i % len(seq)]


def mon_back(n: int) -> dt.date:
    y, m = TODAY.year, TODAY.month - n
    while m <= 0:
        m += 12
        y -= 1
    return dt.date(y, m, 1)


# ==========================================================================
# 0. 清空
# ==========================================================================
# 删除顺序由 ORM 元数据自动推导（见 clear_all），这里不再维护表清单：
# 手写清单漏了 7 张表，导致 --seed 在已有库上必崩。


def clear_all(db: Session) -> None:
    """清空全部业务表（重建演示数据前调用）。

    两个坑，都踩过：

    1. **删除顺序不能手工维护**。这里曾经是一份手写的 `ALL_MODELS` 列表，库里有 65 张表、
       列表里只有 58 张，漏掉的 7 张（`policy_matches`、`contract_payments`、`project_tasks`、
       `user_project_scopes`、`data_quality_*`、`data_uploads`）残留行通过外键挡住父表删除，
       于是 `python run.py --seed` 在**已有库上必然崩溃**，而全新库因为无行可删反而正常——
       这个缺陷在第一次播种时根本看不出来。

    2. **光靠 ORM 拓扑排序也不够**：`contracts` 与 `spaces` 互相引用（循环外键），
       SQLAlchemy 会给出 `Cannot correctly sort tables` 警告，排序结果不可靠，
       照它删依然会撞外键。

    所以整库重置阶段直接**临时关闭外键校验**（SQLite 的标准做法）：先把所有表清空，
    再立刻恢复。注意 `PRAGMA foreign_keys` 在事务内切换无效，必须先 commit 结束事务。
    """
    db.commit()  # 先结束隐式事务，否则 PRAGMA 在事务内切换无效
    # 关键：PRAGMA foreign_keys 是**按连接**生效的，所以必须拿会话正在用的那条
    # 底层连接来执行，并且在整个清空过程中持有它（中途 commit 会让连接代理失效）。
    raw = db.connection().connection.dbapi_connection
    raw.execute("PRAGMA foreign_keys=OFF")
    try:
        for table in Base.metadata.sorted_tables:
            raw.execute(f'DELETE FROM "{table.name}"')
        raw.commit()
    finally:
        raw.execute("PRAGMA foreign_keys=ON")  # 运行期约束必须恢复
        raw.commit()
    db.commit()


# ==========================================================================
# 1. 组织 / 权限 / 角色 / 模板
# ==========================================================================
def seed_organizations(db: Session) -> dict:
    orgs: dict = {}
    group = Organization(
        org_code="ORG-GROUP", org_name="园智汇产业发展集团", short_name="园智汇集团",
        tenant_key="GROUP", contact_person="陈立", contact_phone=phone(1),
        address="江苏省南京市建邺区新城科技园 A 座", status="ACTIVE",
        remark=f"集团总部（多租户根节点）。{LABEL}。",
    )
    db.add(group)
    db.flush()
    orgs["GROUP"] = group

    region = Organization(
        org_code="ORG-EAST", org_name="园智汇集团·华东区域公司", short_name="华东区域",
        tenant_key="REGION", contact_person=cn_name(5), contact_phone=phone(2),
        address="江苏省南京市江北新区研创园", status="ACTIVE",
        remark=f"区域公司。{LABEL}。",
    )
    db.add(region)
    db.flush()
    orgs["REGION"] = region

    for i, pd_ in enumerate(PARK_DEFS):
        sub = Organization(
            org_code=f"ORG-{pd_['code']}",
            org_name=pd_["name"] + "运营有限公司", short_name=pd_["short"],
            tenant_key=pd_["code"], contact_person=cn_name(i * 11 + 3),
            contact_phone=phone(i * 13 + 5),
            address=f"{pd_['city']}{pd_['district']}{pd_['addr']}", status="ACTIVE",
            remark=f"园区运营主体（数据权限隔离单元）。{LABEL}。",
        )
        db.add(sub)
        db.flush()
        orgs[pd_["code"]] = sub
    return orgs


def seed_permissions(db: Session) -> dict:
    perms: dict = {}
    for module, mname in MODULES_FOR_PERM:
        for act, aname in ACTIONS:
            code = f"{module}:{act}"
            p = Permission(perm_code=code, perm_name=f"{mname}-{aname}",
                           module=module, action=act,
                           description=f"{mname}模块的{aname}权限")
            db.add(p)
            perms[code] = p
    db.flush()
    return perms


def seed_roles(db: Session, perms: dict) -> dict:
    roles: dict = {}
    codes = [x[0] for x in ROLES]
    for code, name, cat, scope, desc in ROLES:
        r = Role(role_code=code, role_name=name, role_category=cat,
                 data_scope=scope, description=desc, is_system=True,
                 sort_order=codes.index(code))
        db.add(r)
        roles[code] = r
    db.flush()

    for code, r in roles.items():
        matrix = ROLE_PERM_MATRIX.get(code, {})
        allowed: set = set()
        if "*" in matrix:
            for module, _ in MODULES_FOR_PERM:
                for act in matrix["*"]:
                    allowed.add(f"{module}:{act}")
        else:
            for module, acts in matrix.items():
                for act in acts:
                    allowed.add(f"{module}:{act}")
        for key in allowed:
            p = perms.get(key)
            if p:
                db.add(RolePermission(role_id=r.id, permission_id=p.id))
    db.flush()
    return roles


def seed_templates(db: Session) -> dict:
    out: dict = {}
    for t in PARK_TEMPLATES:
        tpl = ParkTemplate(**t)
        db.add(tpl)
        out[t["template_code"]] = tpl
    db.flush()
    return out


# ==========================================================================
# 2. 园区 / 楼宇 / 楼层 / 空间
# ==========================================================================
PARK_DEFS = [
    {
        "code": "PARK-XH", "name": "星海科技产业园", "short": "星海科技园",
        "type": "TECH", "template": "TPL_TECH",
        "city": "南京市", "district": "江宁区", "addr": "江宁区将军大道 1288 号",
        "total_area": 186000.0, "build_area": 268000.0, "est": d(-2540),
        "mode": "自持运营 + 委托运营",
        "buildings": [
            {"name": "A 栋研发楼", "type": "RESEARCH", "floors": 18, "ug": 2,
             "area": 32400.0, "x": 6, "y": 10, "w": 20, "dd": 22, "h": 78},
            {"name": "B 栋研发楼", "type": "RESEARCH", "floors": 18, "ug": 2,
             "area": 30500.0, "x": 30, "y": 10, "w": 20, "dd": 22, "h": 76},
            {"name": "C 栋孵化器", "type": "INCUBATOR", "floors": 12, "ug": 1,
             "area": 18600.0, "x": 54, "y": 10, "w": 16, "dd": 20, "h": 48},
            {"name": "D 栋标准厂房", "type": "FACTORY", "floors": 5, "ug": 1,
             "area": 42800.0, "x": 6, "y": 44, "w": 30, "dd": 26, "h": 25},
            {"name": "E 栋标准厂房", "type": "FACTORY", "floors": 5, "ug": 1,
             "area": 39200.0, "x": 40, "y": 44, "w": 28, "dd": 26, "h": 24},
            {"name": "F 栋综合服务中心", "type": "SERVICE", "floors": 6, "ug": 2,
             "area": 15600.0, "x": 72, "y": 44, "w": 18, "dd": 24, "h": 30},
            {"name": "G 栋人才公寓", "type": "APARTMENT", "floors": 22, "ug": 2,
             "area": 26400.0, "x": 6, "y": 80, "w": 22, "dd": 14, "h": 68},
            {"name": "H 栋科研中试楼", "type": "RESEARCH", "floors": 8, "ug": 1,
             "area": 19600.0, "x": 34, "y": 80, "w": 20, "dd": 14, "h": 34},
        ],
    },
    {
        "code": "PARK-LG", "name": "临港智能制造产业园", "short": "临港智造园",
        "type": "INDUSTRIAL", "template": "TPL_INDUSTRIAL",
        "city": "南京市", "district": "六合区", "addr": "六合区龙袍街道临港大道 66 号",
        "total_area": 324000.0, "build_area": 412000.0, "est": d(-3100),
        "mode": "自持运营",
        "buildings": [
            {"name": "1# 联合厂房", "type": "FACTORY", "floors": 3, "ug": 0,
             "area": 46200.0, "x": 6, "y": 12, "w": 34, "dd": 30, "h": 20},
            {"name": "2# 联合厂房", "type": "FACTORY", "floors": 3, "ug": 0,
             "area": 44800.0, "x": 46, "y": 12, "w": 34, "dd": 30, "h": 20},
            {"name": "3# 定制厂房", "type": "FACTORY", "floors": 4, "ug": 1,
             "area": 52600.0, "x": 6, "y": 50, "w": 36, "dd": 28, "h": 24},
            {"name": "4# 智能装备车间", "type": "FACTORY", "floors": 3, "ug": 0,
             "area": 38900.0, "x": 48, "y": 50, "w": 32, "dd": 28, "h": 19},
            {"name": "5# 仓储物流中心", "type": "WAREHOUSE", "floors": 2, "ug": 0,
             "area": 57600.0, "x": 6, "y": 86, "w": 40, "dd": 12, "h": 16},
            {"name": "6# 综合办公楼", "type": "OFFICE", "floors": 10, "ug": 2,
             "area": 22800.0, "x": 54, "y": 86, "w": 26, "dd": 12, "h": 42},
        ],
    },
    {
        "code": "PARK-YG", "name": "云谷数字经济产业园", "short": "云谷数字园",
        "type": "TECH", "template": "TPL_TECH",
        "city": "南京市", "district": "雨花台区", "addr": "雨花台区软件大道 168 号",
        "total_area": 96000.0, "build_area": 178000.0, "est": d(-1820),
        "mode": "委托运营",
        "buildings": [
            {"name": "云谷大厦 A 座", "type": "OFFICE", "floors": 26, "ug": 3,
             "area": 42800.0, "x": 8, "y": 14, "w": 24, "dd": 26, "h": 96},
            {"name": "云谷大厦 B 座", "type": "OFFICE", "floors": 22, "ug": 3,
             "area": 38200.0, "x": 40, "y": 14, "w": 22, "dd": 26, "h": 84},
            {"name": "数据中心楼", "type": "DATA_CENTER", "floors": 6, "ug": 1,
             "area": 18600.0, "x": 68, "y": 14, "w": 22, "dd": 24, "h": 30},
            {"name": "云谷孵化器", "type": "INCUBATOR", "floors": 9, "ug": 1,
             "area": 16400.0, "x": 8, "y": 58, "w": 26, "dd": 28, "h": 36},
            {"name": "会议展览中心", "type": "SERVICE", "floors": 4, "ug": 1,
             "area": 12800.0, "x": 44, "y": 58, "w": 26, "dd": 28, "h": 22},
        ],
    },
    {
        "code": "PARK-BS", "name": "滨水科创孵化园", "short": "滨水孵化园",
        "type": "INCUBATOR", "template": "TPL_INCUBATOR",
        "city": "南京市", "district": "浦口区", "addr": "浦口区滨江大道 999 号",
        "total_area": 52000.0, "build_area": 88000.0, "est": d(-1100),
        "mode": "轻资产运营",
        "buildings": [
            {"name": "孵化主楼", "type": "INCUBATOR", "floors": 14, "ug": 2,
             "area": 28600.0, "x": 10, "y": 16, "w": 28, "dd": 34, "h": 52},
            {"name": "众创空间", "type": "INCUBATOR", "floors": 5, "ug": 1,
             "area": 12400.0, "x": 46, "y": 16, "w": 20, "dd": 30, "h": 20},
            {"name": "配套服务中心", "type": "SERVICE", "floors": 3, "ug": 1,
             "area": 8600.0, "x": 10, "y": 62, "w": 26, "dd": 26, "h": 15},
        ],
    },
]

SPACE_PROFILE = {
    "RESEARCH": ("OFFICE", (80, 460), (58, 92), (12, 19)),
    "OFFICE": ("OFFICE", (60, 380), (62, 98), (13, 21)),
    "INCUBATOR": ("OFFICE", (28, 120), (48, 76), (10, 16)),
    "FACTORY": ("FACTORY", (600, 2600), (20, 38), (4.5, 8.5)),
    "WAREHOUSE": ("WAREHOUSE", (800, 3200), (14, 26), (3.5, 6.0)),
    "SERVICE": ("SHOP", (45, 260), (96, 168), (18, 28)),
    "APARTMENT": ("PUBLIC", (35, 90), (42, 68), (8, 13)),
    "DATA_CENTER": ("LAB", (120, 460), (120, 210), (22, 34)),
}


def seed_parks(db: Session, templates: dict, orgs: dict) -> list:
    parks = []
    for i, pd_ in enumerate(PARK_DEFS):
        tpl = templates[pd_["template"]]
        park = Park(
            park_code=pd_["code"], park_name=pd_["name"], short_name=pd_["short"],
            organization_id=orgs[pd_["code"]].id, template_id=tpl.id,
            park_type=pd_["type"], province="江苏省", city=pd_["city"],
            district=pd_["district"], address=pd_["addr"],
            longitude=round(118.72 + i * 0.31, 4), latitude=round(31.92 + i * 0.19, 4),
            total_area=pd_["total_area"], build_area=pd_["build_area"],
            rentable_area=0.0, green_area=round(pd_["total_area"] * 0.18, 2),
            established_date=pd_["est"], manager_name=cn_name(i * 11 + 3),
            contact_phone=phone(i * 13 + 5), operation_mode=pd_["mode"],
            enabled_modules=tpl.enabled_modules, status="ACTIVE",
            remark=f"园区模板：{tpl.template_name}。本园区数据为{LABEL}。",
        )
        db.add(park)
        db.flush()
        parks.append(park)
    return parks


def seed_buildings(db: Session, parks: list) -> tuple:
    buildings, floors, park_spaces = [], [], {}
    for pi, park in enumerate(parks):
        pdef = PARK_DEFS[pi]
        b_area_total = rentable_total = 0.0
        spaces_for_park: list = []
        for bi, bdef in enumerate(pdef["buildings"]):
            b = Building(
                building_code=f"{park.park_code}-B{bi + 1:02d}",
                building_name=bdef["name"], park_id=park.id,
                building_type=bdef["type"], floor_count=bdef["floors"],
                underground_floors=bdef["ug"], build_area=bdef["area"],
                rentable_area=round(bdef["area"] * 0.82, 2),
                map_x=bdef["x"], map_y=bdef["y"], map_w=bdef["w"],
                map_d=bdef["dd"], map_h=bdef["h"],
                completion_date=d(-2400 + pi * 380 + bi * 90),
                property_manager=cn_name(pi * 7 + bi * 3 + 17), status="NORMAL",
                remark=f"数字孪生坐标 x={bdef['x']}% y={bdef['y']}%（园区平面百分比）。{LABEL}。",
            )
            db.add(b)
            db.flush()
            buildings.append(b)

            per_floor = bdef["area"] / bdef["floors"]
            for fi in range(1, bdef["floors"] + 1):
                fl = Floor(
                    floor_code=f"{b.building_code}-F{fi:02d}", floor_name=f"{fi}F",
                    building_id=b.id, park_id=park.id, floor_number=fi,
                    build_area=round(per_floor, 2),
                    rentable_area=round(per_floor * 0.86, 2),
                    usage=("办公" if bdef["type"] in ("RESEARCH", "OFFICE", "SERVICE")
                           else "生产" if bdef["type"] in ("FACTORY", "WAREHOUSE")
                           else "配套"),
                    status="NORMAL",
                )
                db.add(fl)
                db.flush()
                floors.append(fl)

                stype, area_rng, rent_rng, prop_rng = SPACE_PROFILE[bdef["type"]]
                n_units = max(2, int(per_floor / random.uniform(140, 320)))
                consumed = 0.0
                for ui in range(n_units):
                    if ui == n_units - 1:
                        area = round(per_floor * 0.86 - consumed, 2)
                    else:
                        area = round(random.uniform(*area_rng), 2)
                    if area < 20 or consumed + area > per_floor * 0.9:
                        break
                    consumed += area
                    sp = Space(
                        space_code=f"{fl.floor_code}-{ui + 1:03d}",
                        space_name=f"{b.building_name}{fi}F-{ui + 1:03d}",
                        park_id=park.id, building_id=b.id, floor_id=fl.id,
                        space_type=stype, status="AVAILABLE", area=area,
                        rentable_area=round(area * 0.96, 2),
                        rent_price=round(random.uniform(*rent_rng), 2),
                        property_price=round(random.uniform(*prop_rng), 2),
                        orientation=random.choice(["东南", "南", "西南", "东", "西", "北"]),
                        decoration=random.choice(["精装", "简装", "毛坯", "标准装修"]),
                        has_air_conditioner=random.random() < 0.85,
                        vacant_since=d(-random.randint(10, 520)),
                        leasing_status="AVAILABLE",
                        remark=LABEL,
                    )
                    db.add(sp)
                    spaces_for_park.append(sp)
            b_area_total += bdef["area"]
            rentable_total += b.rentable_area
        park.build_area = round(b_area_total, 2)
        park.rentable_area = round(rentable_total, 2)
        park.building_count = len(pdef["buildings"])
        park_spaces[park.id] = spaces_for_park
    db.flush()
    return buildings, floors, park_spaces


def seed_parking(db: Session, parks: list) -> None:
    areas = ["地下车库 B1", "地下车库 B2", "地面停车场 A 区",
             "地面停车场 B 区", "货运装卸区"]
    for pi, park in enumerate(parks):
        n = [900, 1200, 620, 260][pi] if pi < 4 else 260
        for i in range(n):
            area = areas[i % len(areas)]
            ptype = ("CHARGING" if area.startswith("地") and random.random() < 0.16
                     else "FIXED" if random.random() < 0.55 else "TEMPORARY")
            has_charger = ptype == "CHARGING"
            db.add(ParkingSpace(
                space_code=f"PK{park.park_code[-2:]}{i + 1:05d}",
                park_id=park.id, area_name=area, parking_type=ptype,
                space_no=f"{area[0]}-{i + 1:04d}",
                status=random.choices(["OCCUPIED", "AVAILABLE", "RESERVED", "DISABLED"],
                                      weights=[72, 20, 6, 2])[0],
                monthly_fee=round(random.uniform(120, 480), 2),
                has_charger=has_charger,
                charger_power=round(random.uniform(7, 120), 1) if has_charger else None,
            ))
    db.flush()


# ==========================================================================
# 3. 企业
# ==========================================================================
ENTERPRISE_STATUS = ["SETTLED", "SETTLED", "SETTLED", "SETTLED",
                     "GROWING", "POTENTIAL", "EXITED"]
SCALES = ["LARGE", "MEDIUM", "SMALL", "MICRO"]


def cname_kind(industry: str) -> str:
    """把行业映射为企业名称生成风格：制造业 / 物流 / 软件服务。"""
    if any(k in industry for k in ("制造", "装备", "材料", "化工", "汽车", "医药")):
        return "mfG"
    if any(k in industry for k in ("物流", "供应链", "仓储", "运输")):
        return "log"
    return "soft"


def seed_enterprises(db: Session, parks: list) -> list:
    enterprises = []
    counts = [128, 96, 78, 42]
    for pi, park in enumerate(parks):
        n = counts[pi] if pi < len(counts) else 40
        inds = INDUSTRIES
        for i in range(n):
            ind = pick(inds, i + pi)
            scale = random.choices(SCALES, weights=[10, 26, 40, 24])[0]
            emp = {"LARGE": random.randint(320, 2600),
                   "MEDIUM": random.randint(80, 320),
                   "SMALL": random.randint(22, 80),
                   "MICRO": random.randint(4, 22)}[scale]
            revenue = emp * random.uniform(28, 190) * 10000
            status = random.choices(ENTERPRISE_STATUS,
                                    weights=[30, 12, 10, 8, 12, 22, 6])[0]
            risk = random.choices(["LOW", "MEDIUM", "HIGH"], weights=[68, 25, 7])[0]
            name = gen_company_name(i + pi * 131, cname_kind(ind))
            e = Enterprise(
                enterprise_code=f"EN{park.park_code[-2:]}{i + 1:05d}",
                enterprise_name=name, short_name=name[:8],
                unified_social_credit_code=credit_code(i + pi * 997),
                park_id=park.id, industry=ind,
                sub_industry=random.choice(["软件产品", "系统集成", "智能装备",
                                            "新材料制备", "技术检测", "其他"]),
                enterprise_type="LIMITED",
                enterprise_nature=random.choice(["PRIVATE", "STATE", "FOREIGN",
                                                 "JOINT_VENTURE"]),
                status=status,
                register_capital=round(random.uniform(200, 60000) * 10000, 2),
                paid_in_capital=round(random.uniform(100, 40000) * 10000, 2),
                established_date=d(-random.randint(400, 5200)),
                legal_person=cn_name(i * 7 + pi * 23 + 1),
                contact_person=cn_name(i * 5 + pi * 17 + 2),
                contact_phone=phone(i + pi * 61),
                contact_email=f"contact{i + 1}@{park.park_code.lower()}.demo.cn",
                employee_count=emp,
                rnd_employee_count=max(2, int(emp * random.uniform(0.12, 0.62))),
                annual_revenue=round(revenue, 2),
                annual_tax=round(revenue * random.uniform(0.015, 0.062), 2),
                financing_stage=random.choice(["NONE", "SEED", "ANGEL", "A", "B", "C"]),
                financing_amount=round(random.uniform(0, 30000) * 10000, 2),
                ip_count=random.randint(0, 96),
                invention_patent_count=random.randint(0, 32),
                software_copyright_count=random.randint(0, 68),
                is_high_tech=random.random() < 0.34,
                is_specialized=random.random() < 0.13,
                is_little_giant=random.random() < 0.05,
                is_tech_sme=random.random() < 0.29,
                settle_date=d(-random.randint(30, 2100)),
                exit_date=(d(-random.randint(1, 300)) if status == "EXITED" else None),
                leased_area=0.0, risk_level=risk,
                risk_note=("存在租金逾期与经营下滑信号，建议重点关注。"
                           if risk == "HIGH" else
                           "经营稳定，暂无异常。" if risk == "LOW" else
                           "存在个别关注事项。"),
                credit_rating=random.choice(["AAA", "AA", "A", "BBB", "BB"]),
                tags=random.sample(["高新技术企业", "专精特新", "规上企业", "上市后备",
                                    "独角兽", "瞪羚企业", "研发机构", "外资企业"],
                                   k=random.randint(0, 3)),
                description=name + "，主营" + ind + "相关产品与技术服务。",
                is_demo=True,
            )
            db.add(e)
            enterprises.append(e)
        db.flush()
    return enterprises


def assign_spaces(db: Session, parks: list, enterprises: list,
                  park_spaces: dict) -> None:
    by_park: dict = {}
    for e in enterprises:
        by_park.setdefault(e.park_id, []).append(e)

    for park in parks:
        ents = by_park.get(park.id, [])
        spaces = list(park_spaces.get(park.id, []))
        random.shuffle(spaces)
        idx = 0
        for e in ents:
            if e.status not in ("SETTLED", "GROWING"):
                continue
            take = random.choices([1, 1, 1, 2, 2, 3, 4], k=1)[0]
            if idx + take > len(spaces):
                break
            assigned = spaces[idx:idx + take]
            idx += take
            for sp in assigned:
                sp.enterprise_id = e.id
                sp.status = "RENTED"
                sp.leasing_status = "LEASED"
                sp.vacant_since = None
                sp.lease_start = e.settle_date
                sp.lease_end = d(random.randint(60, 1500))
            e.leased_area = round(sum(x.area for x in assigned), 2)
        for sp in spaces[idx:idx + max(3, len(spaces) // 12)]:
            if sp.enterprise_id is None:
                sp.leasing_status = "NEGOTIATING"
                sp.status = "RESERVED"
    db.flush()


def seed_enterprise_contacts_tags(db: Session, enterprises: list) -> None:
    positions = ["总经理", "行政总监", "财务经理", "技术负责人", "人事经理", "生产经理"]
    tags_pool = [
        ("经营规模", "规上企业"), ("创新能力", "高新技术企业"), ("创新能力", "专精特新"),
        ("资本阶段", "已获融资"), ("信用情况", "无逾期记录"), ("信用情况", "有逾期记录"),
        ("安全评级", "A 级"), ("安全评级", "B 级"), ("服务需求", "政策申报"),
        ("服务需求", "人才招聘"), ("风险关注", "经营下滑"), ("风险关注", "租金逾期"),
    ]
    for i, e in enumerate(enterprises):
        for k in range(random.randint(1, 3)):
            db.add(EnterpriseContact(
                enterprise_id=e.id, name=cn_name(i * 3 + k * 7 + 5),
                position=pick(positions, k),
                phone="1" + random.choice("35789") + str(random.randint(10000000, 99999999)),
                email=f"p{k + 1}@{e.enterprise_code.lower()}.demo.cn",
                is_primary=(k == 0), remark=LABEL,
            ))
        for k in range(random.randint(0, 4)):
            tn, tv = random.choice(tags_pool)
            db.add(EnterpriseTag(
                enterprise_id=e.id, tag_name=tv, tag_type=tn, tag_value=tv,
            ))
    db.flush()


# ==========================================================================
# 4. 招商
# ==========================================================================
CHANNEL_DEFS = [
    ("政府推荐", "GOVERNMENT", 0), ("行业协会", "ASSOCIATION", 8000),
    ("中介机构", "AGENCY", 26000), ("线上平台", "ONLINE", 12000),
    ("自有渠道", "OWN", 0), ("以商招商", "REFERRAL", 3000),
    ("展会活动", "EXHIBITION", 18000), ("产业联盟", "ALLIANCE", 6000),
]

LEAD_STAGES = ["LEAD", "CONTACTED", "QUALIFIED", "SITE_VISIT",
               "NEGOTIATION", "CONTRACT_APPROVAL", "SIGNED", "SETTLED", "LOST"]


def seed_channels_activities(db: Session, parks: list) -> tuple:
    channels, acts = [], []
    for park in parks:
        for code, cname, cost in CHANNEL_DEFS:
            ch = Channel(
                channel_code=f"CH{park.park_code[-2:]}{code}", channel_name=cname,
                channel_type=code, park_id=park.id, cost=float(cost),
                remark=f"{cname}渠道。{LABEL}。",
            )
            db.add(ch)
            channels.append(ch)
        db.flush()
        for i in range(18):
            start = d(-random.randint(20, 480))
            ls = random.randint(3, 42)
            sc = random.randint(0, min(ls, 9))
            db.add(LeasingActivity(
                activity_code=f"LA{park.park_code[-2:]}{i + 1:03d}",
                activity_name=pick(["招商推介会", "产业对接会", "园区开放日",
                                    "企业走访月", "行业论坛", "政策宣讲会"], i)
                + f"·第 {i % 4 + 1} 期",
                park_id=park.id,
                activity_type=pick(["推介会", "对接会", "开放日", "走访", "论坛", "宣讲"], i),
                start_date=start,
                end_date=start + dt.timedelta(days=random.randint(1, 3)),
                location=pick(["会议展览中心", "多功能厅", "线上直播", "园区广场"], i),
                budget=round(random.uniform(20000, 380000), 2),
                actual_cost=round(random.uniform(15000, 400000), 2),
                lead_count=ls, sign_count=sc, owner=cn_name(i * 9 + 3),
                status="FINISHED" if start < TODAY else "PLANNED",
            ))
    db.flush()
    return channels, acts


def cname_kind(industry: str) -> str:
    """把行业映射为企业名称生成风格：制造业 / 物流 / 软件服务。"""
    if any(k in industry for k in ("制造", "装备", "材料", "化工", "汽车", "医药")):
        return "mfG"
    if any(k in industry for k in ("物流", "供应链", "仓储", "运输")):
        return "log"
    return "soft"


def seed_leads(db: Session, parks: list, channels: list,
               users_by_park: dict) -> list:
    leads = []
    for pi, park in enumerate(parks):
        n = [260, 180, 150, 90][pi] if pi < 4 else 90
        pch = [c for c in channels if c.park_id == park.id]
        inds = INDUSTRIES
        pou = users_by_park.get(park.id, [])
        for i in range(n):
            stage = random.choices(LEAD_STAGES, weights=[20, 16, 14, 14, 12, 6, 8, 4, 6])[0]
            created = d(-random.randint(5, 400))
            area = round(random.uniform(60, 3600), 2)
            owner = random.choice(pou) if pou else None
            lead = LeasingLead(
                lead_code=f"LD{park.park_code[-2:]}{i + 1:05d}",
                company_name=gen_company_name(i + pi * 211, cname_kind(pick(inds, i + pi * 77))),
                park_id=park.id,
                contact_person=cn_name(i * 3 + pi * 19 + 7),
                contact_phone=phone(i + pi * 37),
                contact_position=pick(["总经理", "投资总监", "行政经理", "项目负责人"], i),
                industry=pick(inds, i + pi * 13),
                channel_id=random.choice(pch).id if pch else None,
                stage=stage,
                stage_entered_at=created + dt.timedelta(days=random.randint(1, 40)),
                owner_id=owner.id if owner else None,
                owner_name=owner.real_name if owner else cn_name(i * 5 + 1),
                demand_area=area,
                demand_budget=round(area * random.uniform(28, 110), 2),
                demand_space_type=random.choice(["OFFICE", "FACTORY", "WAREHOUSE",
                                                 "SHOP", "PUBLIC"]),
                demand_floor=pick(["1-3F", "4-8F", "9-14F", "不限", "高层"], i),
                investment_amount=round(random.uniform(500, 60000) * 10000, 2),
                expected_employees=random.randint(10, 800),
                expected_settle_date=d(random.randint(-60, 300)),
                qualification=pick(["意向明确", "已实地考察", "已提供资料", "待确认"], i),
                score=random.randint(35, 98),
                win_probability=round(random.uniform(0.05, 0.92), 3),
                priority=random.choices(["HIGH", "MEDIUM", "LOW"], weights=[26, 52, 22])[0],
                ai_analysis=("根据企业行业、需求面积与预算综合评估，当前阶段「" + stage
                             + "」，建议"
                             + ("优先跟进并安排现场考察。" if stage in ("NEGOTIATION", "SITE_VISIT")
                                else "持续培育。" if stage in ("LEAD", "CONTACTED")
                                else "纳入已签约台账。")),
                source=random.choice(["渠道推荐", "自主咨询", "活动获取",
                                      "线上留资", "转介绍"]),
                last_followup_at=(created + dt.timedelta(days=random.randint(0, 30))
                                  if random.random() < 0.8 else None),
                next_followup_at=d(random.randint(-20, 30)),
                lost_reason=("租金预算与园区定价差距较大" if stage == "LOST" else None),
                remark=LABEL,
            )
            db.add(lead)
            leads.append(lead)
        db.flush()

    for lead in leads:
        for k in range(random.randint(1, 5)):
            ft = random.choice(["电话", "微信", "拜访", "邮件", "会议"])
            db.add(LeasingFollowup(
                lead_id=lead.id, followup_type=ft,
                content=f"通过{ft}与客户沟通，客户"
                + pick(["对园区配套表示认可", "关注租金优惠", "希望尽快安排看房",
                        "需内部决策", "对政策补贴感兴趣"], k),
                result=pick(["有意向继续沟通", "需再评估", "已获取关键需求", "暂缓"], k),
                followup_by=lead.owner_name,
                followup_at=(lead.stage_entered_at or TODAY)
                - dt.timedelta(days=random.randint(0, 60)),
                next_action=pick(["安排现场考察", "发送报价方案",
                                  "提供政策清单", "再次电话回访"], k),
                next_action_at=d(random.randint(-10, 30)),
            ))
    db.flush()
    return leads


# ==========================================================================
# 5. 合同 / 账单 / 收款
# ==========================================================================
def seed_contracts(db: Session, parks: list, enterprises: list,
                   park_spaces: dict, users_by_park: dict) -> list:
    contracts = []
    for pi, park in enumerate(parks):
        ents = [e for e in enterprises
                if e.park_id == park.id and e.status in ("SETTLED", "GROWING")]
        spaces = park_spaces.get(park.id, [])
        by_ent: dict = {}
        for sp in spaces:
            if sp.enterprise_id:
                by_ent.setdefault(sp.enterprise_id, []).append(sp)
        pou = users_by_park.get(park.id, [])
        for i, e in enumerate(ents):
            assigned = by_ent.get(e.id, [])
            if not assigned:
                continue
            area = round(sum(x.area for x in assigned), 2)
            avg_rent = round(sum(x.rent_price for x in assigned) / len(assigned), 2)
            avg_prop = round(sum(x.property_price for x in assigned) / len(assigned), 2)
            start = e.settle_date or d(-random.randint(60, 1500))
            years = random.choice([1, 2, 3, 3, 5])
            end = start + dt.timedelta(days=365 * years + random.randint(-20, 20))
            if random.random() < 0.24:
                end = TODAY + dt.timedelta(days=random.randint(-70, 90))
                start = end - dt.timedelta(days=365 * years)
            monthly_rent = round(area * avg_rent, 2)
            monthly_prop = round(area * avg_prop, 2)
            status = ("EXPIRED" if end < TODAY else
                      "TERMINATED" if random.random() < 0.03 else
                      "EXPIRING" if (end - TODAY).days <= 90 else "ACTIVE")
            first_space = assigned[0]
            db.add(Contract(
                contract_code=f"CT{park.park_code[-2:]}{start.strftime('%y')}{i + 1:05d}",
                contract_name=e.enterprise_name + "租赁合同",
                contract_type="LEASE", park_id=park.id,
                enterprise_id=e.id, enterprise_name=e.enterprise_name,
                space_id=first_space.id, building_id=first_space.building_id,
                space_name=(first_space.space_name if len(assigned) == 1
                            else f"{first_space.space_name} 等 {len(assigned)} 间"),
                leased_area=area,
                party_a=park.park_name + "运营有限公司", party_b=e.enterprise_name,
                start_date=start, end_date=end,
                sign_date=start - dt.timedelta(days=random.randint(3, 45)),
                rent_price=avg_rent, monthly_rent=monthly_rent,
                property_price=avg_prop, monthly_property_fee=monthly_prop,
                deposit=round((monthly_rent + monthly_prop) * random.choice([2, 3]), 2),
                free_rent_months=random.choice([0, 0, 0, 1, 2, 3]),
                rent_increase_rule=random.choice(["每年递增 3%", "每年递增 5%",
                                                  "第 3 年起递增 5%", "不递增"]),
                payment_cycle=random.choice(["QUARTERLY", "MONTHLY",
                                             "HALF_YEAR", "YEARLY"]),
                payment_day=random.choice([5, 10, 15, 20, 25]),
                contract_amount=round((monthly_rent + monthly_prop) * 12 * years
                                      * random.uniform(0.94, 1.0), 2),
                status=status, approval_status="APPROVED",
                owner_id=(random.choice(pou).id if pou else None),
                owner_name=(random.choice(pou).real_name if pou else cn_name(i + 3)),
                signed_by=cn_name(i * 11 + 9), attachment_count=random.randint(1, 6),
                ai_analysis=("合同将在 90 天内到期，建议提前 60 天启动续约沟通。"
                             if status in ("ACTIVE", "EXPIRING")
                             and (end - TODAY).days <= 90 else "合同执行正常。"),
                remark=LABEL,
            ))
            contracts.append(
                dict(ent=e, area=area, rent=monthly_rent, prop=monthly_prop,
                     start=start, end=end, park_id=park.id, index=i)
            )
        db.flush()
    # 回填 contract id
    db.flush()
    for row in contracts:
        pass
    return contracts


def age_bucket(days: int) -> str:
    if days <= 0:
        return "NORMAL"
    if days <= 30:
        return "D1_30"
    if days <= 90:
        return "D31_90"
    if days <= 180:
        return "D91_180"
    if days <= 365:
        return "D181_365"
    return "OVER_365"


def seed_bills(db: Session, contracts_meta: list, contract_objs: list) -> None:
    for meta in contracts_meta:
        e = meta["ent"]
        monthly_rent = meta["rent"]
        monthly_prop = meta["prop"]
        start = meta["start"]
        park_id = meta["park_id"]
        ent_id = e.id
        ent_name = e.enterprise_name
        for ftype, base in (("RENT", monthly_rent), ("PROPERTY", monthly_prop)):
            if base <= 0:
                continue
            cur = dt.date(start.year, start.month, min(15, 28))
            count = 0
            while cur <= TODAY and count < 80:
                overdue = max((TODAY - cur).days - 15, 0)
                if cur < TODAY and overdue > 0 and random.random() < 0.91:
                    received, status = base, "PAID"
                elif overdue > 0:
                    ratio = random.choice([0.0, 0.0, 0.3, 0.5, 0.7])
                    received = round(base * ratio, 2)
                    status = "PARTIAL" if received > 0 else "OVERDUE"
                else:
                    received = round(base * random.uniform(0, 0.4), 2)
                    status = "PAID" if received >= base * 0.99 else "UNPAID"
                db.add(Bill(
                    bill_code=f"BL{park_id}{ftype[:2]}{cur.strftime('%y%m')}{ent_id:05d}",
                    park_id=park_id, enterprise_id=ent_id, enterprise_name=ent_name,
                    contract_id=None, space_id=None, fee_type=ftype,
                    period=cur.strftime("%Y-%m"), bill_date=cur,
                    due_date=cur + dt.timedelta(days=15),
                    amount=base, discount_amount=0, reduction_amount=0,
                    receivable=base, received=received, refund_amount=0,
                    arrears=round(base - received, 2), status=status,
                    overdue_days=overdue if status != "PAID" else 0,
                    age_bucket=age_bucket(overdue) if status != "PAID" else "NORMAL",
                    invoice_status=("OPENED" if received > 0 else "NOT_OPENED"),
                    invoice_no=(f"INV{cur.strftime('%y%m')}{random.randint(1000, 9999)}"
                                if received > 0 and random.random() < 0.6 else None),
                    dunning_count=(random.randint(1, 4)
                                   if status in ("OVERDUE", "PARTIAL") else 0),
                    last_dunning_at=(cur + dt.timedelta(days=random.randint(16, 60))
                                     if status in ("OVERDUE", "PARTIAL") else None),
                    remark=LABEL,
                ))
                count += 1
                nxt = cur + dt.timedelta(days=31)
                cur = dt.date(nxt.year, nxt.month, min(15, 28))

        # 水电 / 停车 / 服务费
        cur2 = dt.date(max(start.year, TODAY.year - 1), 1, 15)
        for k in range(16):
            if cur2 > TODAY or cur2 < start:
                nxt = cur2 + dt.timedelta(days=31)
                cur2 = dt.date(nxt.year, nxt.month, 15)
                continue
            season = 1.28 if cur2.month in (6, 7, 8, 12, 1) else 1.0
            fee_map = {
                "ELECTRIC": round(meta["area"] * random.uniform(4.2, 7.6) * season, 2),
                "WATER": round(meta["area"] * random.uniform(0.5, 1.4), 2),
                "PARKING": round(random.randint(1, 12) * random.uniform(150, 420), 2),
                "SERVICE": round(random.uniform(0, 6000), 2),
                "MEETING": round(random.uniform(0, 1800), 2),
            }
            for ftype, amt in fee_map.items():
                if amt <= 0:
                    continue
                overdue = max((TODAY - cur2).days - 15, 0)
                if random.random() < (0.90 if ftype != "SERVICE" else 0.72):
                    received = amt
                else:
                    received = round(amt * random.choice([0, 0.4]), 2)
                db.add(Bill(
                    bill_code=f"BL{park_id}{ftype[:2]}{cur2.strftime('%y%m')}{ent_id:05d}x",
                    park_id=park_id, enterprise_id=ent_id, enterprise_name=ent_name,
                    contract_id=None, space_id=None, fee_type=ftype,
                    period=cur2.strftime("%Y-%m"), bill_date=cur2,
                    due_date=cur2 + dt.timedelta(days=15),
                    amount=amt, discount_amount=0, reduction_amount=0,
                    receivable=amt, received=received, refund_amount=0,
                    arrears=round(amt - received, 2),
                    status=("PAID" if received >= amt * 0.99 else
                            "PARTIAL" if received > 0 else "OVERDUE"),
                    overdue_days=overdue if received < amt * 0.99 else 0,
                    age_bucket=(age_bucket(overdue) if received < amt * 0.99 else "NORMAL"),
                    invoice_status="NOT_OPENED",
                    dunning_count=random.randint(0, 2) if received < amt * 0.99 else 0,
                    remark=LABEL,
                ))
            nxt = cur2 + dt.timedelta(days=31)
            cur2 = dt.date(nxt.year, nxt.month, 15)
    db.flush()


def seed_payments(db: Session, limit: int = 6000) -> None:
    bills = db.query(Bill).filter(Bill.received > 0).limit(limit).all()
    for i, b in enumerate(bills):
        n = 1 if abs(b.arrears) < 0.01 else 2
        remain = b.received
        for k in range(n):
            amt = round(remain / (n - k), 2)
            remain = round(remain - amt, 2)
            db.add(Payment(
                payment_code=f"PY{i + 1:07d}{k}",
                bill_id=b.id, contract_id=b.contract_id, park_id=b.park_id,
                enterprise_id=b.enterprise_id, enterprise_name=b.enterprise_name,
                amount=amt,
                pay_date=(b.due_date - dt.timedelta(days=random.randint(0, 18))
                          if b.status == "PAID"
                          else b.due_date + dt.timedelta(days=random.randint(5, 90))),
                pay_method=random.choice(["BANK_TRANSFER", "BANK_TRANSFER",
                                          "ONLINE", "CHECK"]),
                pay_type={"RENT": "租金", "PROPERTY": "物业费", "ELECTRIC": "水电费",
                          "WATER": "水电费", "PARKING": "停车费"}.get(b.fee_type, "服务费"),
                operator=pick(["财务-张", "财务-李", "财务-王", "系统自动核销"], i),
                remark=LABEL,
            ))
    db.flush()


# ==========================================================================
# 6. 项目（瀑布 / 敏捷 / 混合）
# ==========================================================================
WATERFALL_PHASES = {
    "PARK_CONSTRUCTION": [
        {"name": "立项与可研", "weight": 6}, {"name": "方案设计", "weight": 10},
        {"name": "招标采购", "weight": 12}, {"name": "土建施工", "weight": 34},
        {"name": "机电安装", "weight": 18}, {"name": "装饰装修", "weight": 10},
        {"name": "竣工验收", "weight": 6}, {"name": "结算移交", "weight": 4},
    ],
    "FACTORY_RENOVATION": [
        {"name": "立项与评估", "weight": 8}, {"name": "改造方案设计", "weight": 14},
        {"name": "招标采购", "weight": 12}, {"name": "拆除与结构加固", "weight": 20},
        {"name": "机电与工艺管线", "weight": 22}, {"name": "装饰与验收", "weight": 16},
        {"name": "结算移交", "weight": 8},
    ],
    "SOFTWARE": [
        {"name": "需求分析", "weight": 12}, {"name": "总体设计", "weight": 14},
        {"name": "开发实施", "weight": 40}, {"name": "测试与试运行", "weight": 20},
        {"name": "上线验收", "weight": 14},
    ],
    "EQUIPMENT_INSTALL": [
        {"name": "需求确认", "weight": 12}, {"name": "招标采购", "weight": 24},
        {"name": "到货与安装", "weight": 34}, {"name": "调试验收", "weight": 20},
        {"name": "结算归档", "weight": 10},
    ],
    "INFRASTRUCTURE": [
        {"name": "立项与勘察", "weight": 8}, {"name": "方案设计", "weight": 12},
        {"name": "招标采购", "weight": 10}, {"name": "市政施工", "weight": 42},
        {"name": "检测验收", "weight": 18}, {"name": "结算移交", "weight": 10},
    ],
    "ENERGY_SAVING": [
        {"name": "能源诊断", "weight": 16}, {"name": "方案设计", "weight": 16},
        {"name": "设备采购", "weight": 20}, {"name": "改造实施", "weight": 30},
        {"name": "效果验证", "weight": 18},
    ],
}

WBS_T = {
    "PARK_CONSTRUCTION": [
        (0, "项目建议书编制", 1.4, 60), (0, "可行性研究报告", 2.0, 120),
        (0, "投资估算与评审", 1.0, 60),
        (1, "总体规划方案", 2.4, 160), (1, "建筑与结构施工图", 3.6, 320),
        (1, "机电专业设计", 2.0, 180), (1, "图纸会审与交底", 0.8, 40),
        (2, "施工总承包招标", 3.0, 200), (2, "监理单位招标", 1.2, 60),
        (2, "主要设备采购", 4.0, 240),
        (3, "桩基与基础工程", 4.0, 400), (3, "主体结构施工", 9.0, 900),
        (3, "屋面与外立面", 3.0, 260), (3, "室内粗装修", 3.0, 240),
        (4, "给排水与消防管道", 3.4, 300), (4, "强弱电与智能化", 4.4, 380),
        (4, "暖通空调系统", 4.0, 340), (4, "电梯安装与调试", 2.2, 160),
        (5, "公共区域精装修", 4.0, 320), (5, "园区景观绿化", 2.4, 200),
        (5, "标识与导视系统", 0.8, 60),
        (6, "单机与联动调试", 1.6, 120), (6, "消防与专项验收", 1.6, 120),
        (6, "竣工资料归档", 1.0, 80),
        (7, "工程结算审核", 2.0, 140), (7, "资产移交与保修", 1.4, 100),
    ],
    "FACTORY_RENOVATION": [
        (0, "现状检测与安全评估", 3.0, 120), (0, "改造投资估算", 2.0, 80),
        (1, "改造方案与工艺布局", 5.0, 260), (1, "结构加固设计", 4.0, 200),
        (1, "机电改造设计", 3.0, 160),
        (2, "施工单位招标", 5.0, 200), (2, "主要材料采购", 4.0, 180),
        (3, "原有设施拆除", 4.0, 200), (3, "结构加固施工", 6.0, 320),
        (3, "屋面防水修复", 2.0, 120),
        (4, "工艺管线安装", 6.0, 340), (4, "供配电系统扩容", 5.0, 260),
        (4, "洁净车间与通风", 4.5, 240),
        (5, "地面与墙面装饰", 4.0, 220), (5, "消防系统改造", 3.0, 160),
        (5, "设备调试与试生产", 3.5, 200),
        (6, "专项验收", 3.0, 150), (6, "工程结算与移交", 2.5, 140),
    ],
    "SOFTWARE": [
        (0, "业务需求调研", 4.0, 200), (0, "需求规格说明书", 3.0, 160),
        (0, "需求评审确认", 1.5, 80),
        (1, "系统总体架构设计", 4.0, 200), (1, "数据库设计", 3.0, 150),
        (1, "接口规范设计", 2.5, 130),
        (2, "基础框架搭建", 3.5, 180), (2, "核心模块开发", 10.0, 620),
        (2, "前端界面开发", 7.0, 420), (2, "AI Agent 能力开发", 6.0, 380),
        (2, "系统集成联调", 4.5, 260),
        (3, "单元与集成测试", 5.0, 280), (3, "性能与安全测试", 3.5, 180),
        (3, "用户验收测试", 4.0, 200),
        (4, "生产环境部署", 2.5, 120), (4, "用户培训与手册", 3.0, 140),
        (4, "上线支持与验收", 3.0, 150),
    ],
    "EQUIPMENT_INSTALL": [
        (0, "设备需求与技术参数确认", 4.0, 140), (0, "预算与立项审批", 3.0, 100),
        (1, "供应商资格审查", 2.5, 80), (1, "招标与商务谈判", 5.0, 180),
        (1, "合同签订", 2.0, 60),
        (2, "设备生产与催交", 7.0, 220), (2, "到货验收", 2.5, 90),
        (2, "安装就位", 5.0, 200),
        (3, "单机调试", 3.5, 140), (3, "联动试运行", 4.0, 160),
        (3, "性能指标验证", 3.0, 120),
        (4, "尾款结算", 2.5, 80), (4, "设备档案归档", 1.5, 60),
    ],
    "INFRASTRUCTURE": [
        (0, "项目立项", 2.5, 100), (0, "地质勘察", 3.5, 140), (0, "管线物探", 2.5, 100),
        (1, "道路与管网方案", 4.5, 180), (1, "施工图设计", 4.0, 160),
        (2, "施工招标", 3.5, 120), (2, "材料采购", 3.0, 100),
        (3, "道路路基施工", 6.0, 280), (3, "雨污水管网施工", 6.0, 280),
        (3, "给水与电力管线", 5.0, 240), (3, "照明与交通设施", 3.0, 140),
        (4, "压实度与闭水检测", 3.0, 120), (4, "竣工验收", 3.0, 120),
        (5, "工程结算", 2.5, 100), (5, "移交管养单位", 2.0, 80),
    ],
    "ENERGY_SAVING": [
        (0, "能耗数据采集", 3.0, 120), (0, "节能潜力分析", 4.0, 160),
        (0, "节能量核算基线", 2.5, 100),
        (1, "技术方案比选", 4.0, 160), (1, "投资回收期测算", 2.5, 100),
        (2, "设备采购", 5.0, 200), (2, "施工安装", 5.0, 200),
        (3, "控制系统改造", 6.0, 240), (3, "运行策略优化", 4.0, 160),
        (3, "系统联调", 4.5, 180),
        (4, "节能量测量与验证", 5.0, 200), (4, "效果评估报告", 3.0, 120),
    ],
}

WF_PROJECT_DEFS = [
    (0, "A栋厂房改造工程", "FACTORY_RENOVATION", 5_000_000, -95, 200, 62.0, "IN_PROGRESS", "HIGH"),
    (0, "星海园区智慧能源改造", "ENERGY_SAVING", 3_600_000, -180, 120, 71.0, "IN_PROGRESS", "MEDIUM"),
    (0, "园区雨污分流管网改造", "INFRASTRUCTURE", 8_200_000, -300, 90, 88.0, "IN_PROGRESS", "MEDIUM"),
    (0, "星海园区二期配套工程", "PARK_CONSTRUCTION", 46_000_000, -520, 380, 41.0, "IN_PROGRESS", "HIGH"),
    (0, "园区安防系统升级项目", "EQUIPMENT_INSTALL", 4_800_000, -260, -30, 100.0, "COMPLETED", "LOW"),
    (1, "3#定制厂房建设", "PARK_CONSTRUCTION", 28_500_000, -420, 480, 71.0, "IN_PROGRESS", "HIGH"),
    (1, "临港园区配电扩容工程", "INFRASTRUCTURE", 12_600_000, -210, 160, 55.0, "IN_PROGRESS", "HIGH"),
    (1, "5#仓储物流中心改造", "FACTORY_RENOVATION", 9_800_000, -340, 60, 92.0, "IN_PROGRESS", "MEDIUM"),
    (1, "临港园区空压系统节能改造", "ENERGY_SAVING", 2_800_000, -300, -60, 100.0, "COMPLETED", "LOW"),
    (1, "园区消防设施改造工程", "INFRASTRUCTURE", 6_400_000, -150, 210, 48.0, "IN_PROGRESS", "MEDIUM"),
    (2, "云谷大厦智能化升级", "SOFTWARE", 7_200_000, -240, 120, 68.0, "IN_PROGRESS", "MEDIUM"),
    (2, "数据中心冷却系统改造", "ENERGY_SAVING", 5_400_000, -280, 40, 84.0, "IN_PROGRESS", "MEDIUM"),
    (2, "云谷园区充电桩建设", "EQUIPMENT_INSTALL", 3_200_000, -120, 150, 36.0, "IN_PROGRESS", "LOW"),
    (3, "滨水园区景观提升工程", "INFRASTRUCTURE", 4_600_000, -200, -20, 100.0, "COMPLETED", "LOW"),
    (3, "孵化主楼装修工程", "FACTORY_RENOVATION", 6_800_000, -130, 130, 52.0, "IN_PROGRESS", "MEDIUM"),
]

AG_PROJECT_DEFS = [
    (0, "园区智慧运营平台建设", "SOFTWARE", 12_600_000, -260, 160, 58.0, "IN_PROGRESS", "MEDIUM"),
    (2, "云谷数字孪生平台", "SOFTWARE", 8_400_000, -180, 200, 44.0, "IN_PROGRESS", "MEDIUM"),
    (1, "临港园区数字运营平台", "SOFTWARE", 9_600_000, -140, 240, 32.0, "IN_PROGRESS", "LOW"),
    (0, "园区企业服务平台", "SOFTWARE", 5_200_000, -400, -50, 100.0, "COMPLETED", "LOW"),
]

PROJECT_SCOPE = {
    "FACTORY_RENOVATION": "厂房本体改造、结构加固、机电与工艺管线、消防与验收。",
    "ENERGY_SAVING": "能源审计、设备采购、控制系统改造、节能量验证。",
    "INFRASTRUCTURE": "管线改造、道路与管网、附属设施、检测验收。",
    "PARK_CONSTRUCTION": "土建、安装、装饰、市政配套、竣工验收与结算。",
    "EQUIPMENT_INSTALL": "设备选型、招标采购、安装调试、验收结算。",
    "SOFTWARE": "需求、设计、开发、测试、部署、培训与验收。",
}


def seed_projects(db: Session, parks: list, users_by_park: dict) -> tuple:
    projects, agile_map = [], {}
    idx = 0

    for pi, name, ptype, budget, so, eo, prog, status, risk in WF_PROJECT_DEFS:
        park = parks[pi]
        idx += 1
        pou = users_by_park.get(park.id, [])
        pm = random.choice(pou) if pou else None
        start, end = d(so), d(eo)
        planned_prog = min(100.0, max(5.0, (TODAY - start).days
                                      / max((end - start).days, 1) * 100))
        actual = round(budget * prog / 100 * random.uniform(0.88, 1.16), 2)
        p = Project(
            project_code=f"PRJ{idx:05d}", project_name=name, park_id=park.id,
            project_type=ptype, management_method="WATERFALL",
            project_manager_id=pm.id if pm else None,
            project_manager_name=pm.real_name if pm else cn_name(idx * 7 + 1),
            department=pick(["工程管理部", "数字化部", "运营管理部", "基建部"], idx),
            description=f"{park.park_name}「{name}」，采用瀑布式管理，"
                        f"覆盖从立项到验收结算的全过程。",
            objective=f"按期、按质、按预算完成「{name}」建设目标。",
            scope=PROJECT_SCOPE.get(ptype, "项目全过程管理。"),
            start_date=start, planned_end_date=end, baseline_end_date=end,
            actual_end_date=(end - dt.timedelta(days=random.randint(0, 12))
                             if status == "COMPLETED" else None),
            budget=float(budget), approved_budget=float(budget),
            actual_cost=actual,
            committed_cost=round(budget * random.uniform(0.55, 1.05), 2),
            paid_amount=round(actual * random.uniform(0.72, 0.96), 2),
            progress=prog, planned_progress=round(planned_prog, 2),
            risk_level=risk, priority=random.choice(["HIGH", "MEDIUM", "MEDIUM"]),
            status=status, team_size=random.randint(6, 28),
            is_demo=True, remark=LABEL,
        )
        db.add(p)
        db.flush()
        projects.append(p)

    for pi, name, ptype, budget, so, eo, prog, status, risk in AG_PROJECT_DEFS:
        park = parks[pi]
        idx += 1
        pou = users_by_park.get(park.id, [])
        pm = random.choice(pou) if pou else None
        start, end = d(so), d(eo)
        p = Project(
            project_code=f"PRJ{idx:05d}", project_name=name, park_id=park.id,
            project_type=ptype, management_method="AGILE",
            project_manager_id=pm.id if pm else None,
            project_manager_name=pm.real_name if pm else cn_name(idx * 7 + 1),
            department="数字化部",
            description=f"{park.park_name}「{name}」，采用敏捷管理，"
                        f"以 Epic / Feature / User Story 组织需求，按 Sprint 迭代交付。",
            objective="以 2 周为一个迭代，持续交付可用软件能力。",
            scope="按 Epic 组织：数据底座 → 驾驶舱 → 项目管理 → AI 智能体 → 权限审批。",
            start_date=start, planned_end_date=end, baseline_end_date=end,
            budget=float(budget), approved_budget=float(budget),
            actual_cost=round(budget * prog / 100 * random.uniform(0.9, 1.2), 2),
            committed_cost=round(budget * random.uniform(0.5, 0.95), 2),
            paid_amount=round(budget * prog / 100 * random.uniform(0.7, 0.95), 2),
            progress=prog,
            planned_progress=round(min(100.0, max(5.0, (TODAY - start).days
                                                  / max((end - start).days, 1) * 100)), 2),
            risk_level=risk, priority="HIGH", status=status,
            team_size=random.randint(8, 18), is_demo=True, remark=LABEL,
        )
        db.add(p)
        db.flush()
        projects.append(p)
        agile_map[p.id] = (ptype, start, end)

    # 混合项目：父项目瀑布 + 子项目敏捷
    park = parks[0]
    idx += 1
    pou = users_by_park.get(park.id, [])
    hp_pm = next((u for u in pou if u.username == "pm_digital"),
                 random.choice(pou) if pou else None)
    hp = Project(
        project_code=f"PRJ{idx:05d}", project_name="智慧园区数字化平台建设",
        park_id=park.id, project_type="SOFTWARE", management_method="HYBRID",
        project_manager_id=hp_pm.id if hp_pm else None,
        project_manager_name=hp_pm.real_name if hp_pm else cn_name(31),
        department="数字化部",
        description="总体按瀑布管理推进（立项→需求→总体设计→采购→建设→实施→验收），"
                    "其中软件平台开发以敏捷子项目实施，按 Sprint 交付。",
        objective="建成可配置、可复制、可扩展的园区数字运营平台。",
        scope="需求分析、总体设计、采购、建设、实施、验收；软件平台开发采用敏捷迭代。",
        start_date=d(-260), planned_end_date=d(160), baseline_end_date=d(160),
        budget=12_600_000.0, approved_budget=12_600_000.0,
        actual_cost=round(12_600_000 * 0.58 * random.uniform(0.94, 1.10), 2),
        committed_cost=round(12_600_000 * 0.72, 2),
        progress=58.0,
        planned_progress=round(min(100.0, (TODAY - d(-260)).days / 420 * 100), 2),
        risk_level="MEDIUM", priority="HIGH", status="IN_PROGRESS",
        team_size=18, is_demo=True,
        remark="混合式管理：父项目瀑布 + 子项目敏捷。" + LABEL,
    )
    hp.paid_amount = round(hp.actual_cost * random.uniform(0.78, 0.94), 2)
    db.add(hp)
    db.flush()
    projects.append(hp)

    idx += 1
    sub = Project(
        project_code=f"PRJ{idx:05d}", project_name="智慧园区平台·软件平台开发子项目",
        park_id=park.id, parent_project_id=hp.id, project_type="SOFTWARE",
        management_method="AGILE",
        project_manager_id=hp.project_manager_id,
        project_manager_name=hp.project_manager_name,
        department="数字化部",
        description=f"父项目「{hp.project_name}」的软件平台开发子项目，采用敏捷管理。",
        start_date=d(-240), planned_end_date=d(120),
        budget=4_800_000.0, approved_budget=4_800_000.0,
        actual_cost=round(4_800_000 * 0.62, 2),
        committed_cost=round(4_800_000 * 0.75, 2),
        progress=62.0,
        planned_progress=round(min(100.0, (TODAY - d(-240)).days / 360 * 100), 2),
        risk_level="MEDIUM", priority="HIGH", status="IN_PROGRESS",
        team_size=12, is_demo=True, remark=LABEL,
    )
    sub.paid_amount = round(sub.actual_cost * 0.85, 2)
    db.add(sub)
    db.flush()
    projects.append(sub)
    agile_map[sub.id] = ("SOFTWARE", sub.start_date, sub.planned_end_date)

    return projects, agile_map, hp, sub


# ==========================================================================
# 7. 阶段 / WBS / 依赖 / 敏捷结构
# ==========================================================================
def seed_phases_wbs(db: Session, projects: list, agile_map: dict) -> dict:
    wbs_cache: dict = {}
    for p in projects:
        if p.management_method in ("WATERFALL", "HYBRID"):
            phases = WATERFALL_PHASES.get(p.project_type,
                                          WATERFALL_PHASES["INFRASTRUCTURE"])
            wbs_defs = WBS_T.get(p.project_type, WBS_T["INFRASTRUCTURE"])
            total_w = sum(x[2] for x in wbs_defs) or 1
            span = max((p.planned_end_date - p.start_date).days, 30)

            phase_rows: list = []
            cursor = p.start_date
            for i, ph in enumerate(phases):
                dur = max(int(span * ph["weight"] / 100), 5)
                st_, en_ = cursor, cursor + dt.timedelta(days=dur)
                pg = min(100.0, max(0.0, (TODAY - st_).days / max((en_ - st_).days, 1) * 100))
                if en_ < TODAY:
                    pg = 100.0
                row = ProjectPhase(
                    project_id=p.id,
                    phase_code=f"PH{i + 1:02d}", phase_name=ph["name"],
                    phase_order=i + 1, start_date=st_, end_date=en_,
                    progress=round(pg, 2),
                    status=("COMPLETED" if pg >= 100 else
                            "IN_PROGRESS" if pg > 0 else "NOT_STARTED"),
                    owner=pick([p.project_manager_name, "工程管理部", "项目管理办公室"], i),
                    deliverable=pick(["批复文件", "设计图纸", "中标通知", "施工记录",
                                      "调试报告", "验收证书", "结算书", "移交单"], i),
                )
                db.add(row)
                phase_rows.append(row)
                cursor = en_
            db.flush()

            leaves: list = []
            order = 0
            for pi, ph in enumerate(phases):
                parent = WbsItem(
                    project_id=p.id, wbs_code=str(pi + 1), item_name=ph["name"],
                    item_level=1, item_type="SUMMARY", sort_order=pi,
                    phase_id=phase_rows[pi].id,
                    plan_start=phase_rows[pi].start_date,
                    plan_end=phase_rows[pi].end_date,
                    weight=ph["weight"], progress=phase_rows[pi].progress,
                )
                db.add(parent)
                db.flush()
                subs = [x for x in wbs_defs if x[0] == pi]
                if not subs:
                    subs = [(pi, ph["name"] + "·实施", ph["weight"], 80)]
                sub_total = sum(x[2] for x in subs) or 1
                p_span = (phase_rows[pi].end_date - phase_rows[pi].start_date).days
                for si, (_, sname, sweight, shours) in enumerate(subs):
                    order += 1
                    dur = max(int(p_span * sweight / sub_total), 3)
                    st_ = phase_rows[pi].start_date + dt.timedelta(
                        days=int(p_span * si / max(len(subs), 1)))
                    en_ = st_ + dt.timedelta(days=dur)
                    drift = random.choice([0.0, 0.0, 0.0, 0.12, 0.25, 0.4])
                    pr = (round(min(100.0, max(0.0, p.progress * (1 - drift))), 2)
                          if en_ >= TODAY else 100.0)
                    if p.status == "COMPLETED":
                        pr = 100.0
                    leaf = WbsItem(
                        project_id=p.id, parent_id=parent.id,
                        wbs_code=f"{pi + 1}.{si + 1}", item_name=sname,
                        item_level=2, item_type="TASK", sort_order=order,
                        phase_id=phase_rows[pi].id,
                        plan_start=st_, plan_end=en_,
                        actual_start=st_ if pr > 0 else None,
                        actual_end=en_ if pr >= 100 else None,
                        duration_days=dur,
                        progress=pr,
                        weight=round(sweight / total_w * 100, 2),
                        budget=round(p.budget * sweight / total_w, 2),
                        actual_cost=round(p.budget * sweight / total_w * pr / 100
                                          * random.uniform(0.9, 1.25), 2),
                        status=("DONE" if pr >= 100 else
                                "IN_PROGRESS" if pr > 0 else "TODO"),
                        risk_level=random.choices(["LOW", "MEDIUM", "HIGH"],
                                                  weights=[60, 32, 8])[0],
                        is_critical=False,
                        owner_name=pick([p.project_manager_name, "工程管理部", "采购部",
                                         "技术部", "监理单位", "施工单位"], si + pi),
                        responsible_role=pick(["项目经理", "专业工程师", "采购专员",
                                               "施工负责人"], si),
                        deliverable=sname + "交付物",
                    )
                    db.add(leaf)
                    leaves.append(leaf)
            db.flush()

            for a, b in zip(leaves, leaves[1:]):
                db.add(TaskDependency(
                    project_id=p.id, predecessor_id=a.id, successor_id=b.id,
                    dep_type="SS" if random.random() < 0.12 else "FS",
                    lag_days=random.choice([0, 0, 0, 1, 2]),
                ))
            by_phase: dict = {}
            for lf in leaves:
                by_phase.setdefault(lf.phase_id, []).append(lf)
            for _pid, lst in by_phase.items():
                if len(lst) >= 3 and random.random() < 0.5:
                    db.add(TaskDependency(
                        project_id=p.id, predecessor_id=lst[0].id,
                        successor_id=lst[2].id, dep_type="FS", lag_days=1,
                    ))
            db.flush()

            # CPM 计算并回写关键路径（引擎自身负责写回 slack_days / is_critical）
            try:
                from app.services.project_engine import compute_critical_path
                compute_critical_path(db, p.id)
                db.flush()
            except Exception:
                db.rollback()

            wbs_cache[p.id] = leaves

        if p.management_method == "AGILE":
            seed_agile(db, p, agile_map.get(p.id, (p.project_type,
                                                   p.start_date, p.planned_end_date)))
    return wbs_cache


AGILE_GOALS = [
    "打通园区核心数据底座，完成主数据接入",
    "完成运营驾驶舱与关键 KPI 上线",
    "完成 AI Agent 工具链与意图路由",
    "完成审批中心与权限体系联动",
    "完成移动端适配与消息触达",
    "完成性能优化与安全加固",
    "完成试点园区上线与用户培训",
    "完成数据质量校验与治理闭环",
]

AGILE_EPICS = [
    {"name": "数据底座与主数据治理",
     "desc": "统一园区主数据、企业数据、空间数据与财务数据模型",
     "bv": "HIGH", "pri": "P0",
     "features": ["数据模型设计", "主数据接入", "数据质量校验", "数据溯源"]},
    {"name": "运营驾驶舱与可视化",
     "desc": "构建集团/园区/楼宇三级驾驶舱与数字孪生视图",
     "bv": "HIGH", "pri": "P0",
     "features": ["园区总览驾驶舱", "数字孪生一园一图", "KPI 下钻", "移动端适配"]},
    {"name": "项目管理中心", "desc": "瀑布/敏捷/混合项目全流程管理能力",
     "bv": "HIGH", "pri": "P1",
     "features": ["WBS 与甘特图", "关键路径计算", "挣值分析", "敏捷看板"]},
    {"name": "AI 智能体体系", "desc": "主 Agent + 子 Agent 编排、工具调用与可追溯回答",
     "bv": "HIGH", "pri": "P1",
     "features": ["意图识别与路由", "Agent 工具链", "证据链输出", "风险识别"]},
    {"name": "审批中心与权限体系", "desc": "三级 AI 权限、人工审批与数据权限隔离",
     "bv": "MEDIUM", "pri": "P1",
     "features": ["角色权限矩阵", "数据权限范围", "审批流引擎", "审计日志"]},
    {"name": "财务与合同管理", "desc": "租金账单、收款、欠费与合同全生命周期",
     "bv": "MEDIUM", "pri": "P2",
     "features": ["账单与收款", "欠费账龄", "合同到期预警", "开票管理"]},
]


def seed_agile(db: Session, p: Project, meta: tuple) -> None:
    _ptype, start, end = meta
    sprint_len = 14
    n = max(3, int((end - start).days / sprint_len))
    sprints: list = []
    for si in range(n):
        s_start = start + dt.timedelta(days=si * sprint_len)
        s_end = s_start + dt.timedelta(days=sprint_len - 1)
        stt = ("COMPLETED" if s_end < TODAY else
               "ACTIVE" if s_start <= TODAY <= s_end else "PLANNED")
        cap = random.randint(48, 72)
        done = cap if stt == "COMPLETED" else (
            int(cap * random.uniform(0.45, 0.9)) if stt == "ACTIVE" else 0)
        sp = Sprint(
            project_id=p.id, sprint_code=f"SP{si + 1:02d}",
            sprint_name=f"Sprint {si + 1}", sprint_goal=pick(AGILE_GOALS, si),
            start_date=s_start, end_date=s_end,
            owner=p.project_manager_name,
            story_count=0, total_points=cap, done_points=done,
            completed_rate=round(done / cap * 100, 2),
            velocity=(round(sum(random.uniform(38, 66) for _ in range(min(si, 3)))
                            / max(min(si, 3), 1), 2) if si >= 3 else None),
            status=stt,
            review_summary=("迭代目标达成，已交付可用能力。" if stt == "COMPLETED" else None),
            retro_summary=("需求变更较多，下个迭代加强评审。" if stt == "COMPLETED" else None),
        )
        db.add(sp)
        db.flush()
        sprints.append(sp)

    for ei, e in enumerate(AGILE_EPICS):
        ep_status = ("DONE" if p.progress > 70 and ei < 2 else
                     "IN_PROGRESS" if ei < 4 else "TODO")
        ep = Epic(
            project_id=p.id, epic_code=f"EP{ei + 1:02d}", epic_title=e["name"],
            description=e["desc"], owner=p.project_manager_name,
            priority=e["pri"], status=ep_status,
            story_points=random.choice([34, 55, 89]), start_date=d(-250 + ei * 20),
            target_date=d(120 - ei * 15),
        )
        db.add(ep)
        db.flush()
        for fi, f in enumerate(e["features"]):
            ft = Feature(
                project_id=p.id, epic_id=ep.id, feature_code=f"FT{ei + 1:02d}{fi + 1:02d}",
                feature_title=f, description=f + "的实现能力。",
                owner=pick(["产品经理", p.project_manager_name, "技术负责人"], fi),
                priority=pick(["HIGH", "MEDIUM", "MEDIUM", "LOW"], fi),
                status=("DONE" if ei == 0 else
                        "IN_PROGRESS" if ei < 4 else "TODO"),
                story_points=random.choice([8, 13, 21]),
            )
            db.add(ft)
            db.flush()
            for ui in range(random.randint(2, 4)):
                stage = random.choice(["TODO", "TODO", "IN_PROGRESS",
                                       "TESTING", "DONE", "DONE"])
                pts = random.choice([2, 3, 3, 5, 5, 8, 13])
                sp_t = sprints[min(ei * 2 + ui // 2, len(sprints) - 1)]
                db.add(UserStory(
                    project_id=p.id, feature_id=ft.id,
                    story_code=f"US{ei + 1:02d}{fi + 1:02d}{ui + 1:02d}",
                    story_title=f + f"·用户故事 {ui + 1}",
                    as_a="园区运营人员",
                    i_want=f + f"（场景 {ui + 1}）",
                    so_that="提升运营效率、减少人工统计工作量",
                    acceptance_criteria="功能可用且通过验收用例；关键字段可追溯来源。",
                    story_point=pts,
                    priority=pick(["HIGH", "MEDIUM", "LOW"], ui),
                    status=stage,
                    assignee_name=pick(["研发A", "研发B", "研发C", "测试A", "产品A"], ui),
                    sprint_id=sp_t.id, backlog_order=ui,
                ))
                db.add(SprintTask(
                    sprint_id=sp_t.id, project_id=p.id,
                    task_code=f"TK{ei + 1:02d}{fi + 1:02d}{ui + 1:02d}",
                    task_title=f + f"·任务 {ui + 1}",
                    board_column=({"TODO": "TODO", "IN_PROGRESS": "IN_PROGRESS",
                                   "TESTING": "TESTING", "DONE": "DONE"}[stage]
                                  if stage in ("TODO", "IN_PROGRESS", "TESTING", "DONE")
                                  else "BACKLOG"),
                    story_point=pts, priority=pick(["HIGH", "MEDIUM", "LOW"], ui),
                    assignee_name=pick(["研发A", "研发B", "研发C"], ui),
                    estimate_hours=round(pts * random.uniform(3, 5), 1),
                    actual_hours=round(pts * random.uniform(2, 6), 1),
                    column_order=ui,
                ))
    db.flush()

    for sp_ in sprints:
        stories = db.query(UserStory).filter(UserStory.sprint_id == sp_.id).all()
        sp_.story_count = len(stories)
        if sp_.status == "COMPLETED":
            for st_ in stories:
                st_.status = "DONE"
                st_.story_point = st_.story_point or 3
        sp_.total_points = sum(x.story_point or 0 for x in stories) or sp_.total_points
        sp_.done_points = sum(x.story_point or 0 for x in stories
                              if x.status == "DONE")
        sp_.completed_rate = round(sp_.done_points / max(sp_.total_points, 1) * 100, 2)
        pts = [x.story_point or 0 for x in stories]
        committed = sum(pts)
        burndown = []
        for day in range((sp_.end_date - sp_.start_date).days + 1):
            cur = sp_.start_date + dt.timedelta(days=day)
            ideal = committed * (1 - day / max((sp_.end_date - sp_.start_date).days, 1))
            if sp_.status == "COMPLETED":
                remaining = committed * (1 - day / max((sp_.end_date - sp_.start_date).days, 1))
            elif sp_.status == "ACTIVE" and cur <= TODAY:
                prog = (cur - sp_.start_date).days / max(
                    (sp_.end_date - sp_.start_date).days, 1)
                remaining = committed * (1 - min(prog, 0.9)) * random.uniform(0.85, 1.15)
            else:
                remaining = committed
            burndown.append({
                "date": cur.isoformat(), "ideal": round(ideal, 1),
                "remaining": round(remaining, 1),
            })
        sp_.burndown = burndown
    db.flush()


# ==========================================================================
# 8. 里程碑 / 成本 / 风险 / 问题 / 变更
# ==========================================================================
MILESTONE_TEMPLATE = [
    ("立项批复", "MS01", 0.04), ("方案评审通过", "MS02", 0.16),
    ("开工", "MS03", 0.28), ("主体完成", "MS04", 0.55),
    ("联调试运行", "MS05", 0.78), ("竣工验收", "MS06", 0.94),
    ("结算完成", "MS07", 1.0),
]

RISK_LIBRARY = [
    ("关键路径任务受外部审批影响存在延期可能", "SCHEDULE"),
    ("材料与人工价格上涨导致预算超支", "COST"),
    ("施工/开发质量不达标需返工", "QUALITY"),
    ("现场作业存在安全作业风险", "SAFETY"),
    ("关键设备/材料供货周期延长", "PROCUREMENT"),
    ("相关审批手续办理滞后", "COMPLIANCE"),
    ("关键岗位人员投入不足", "RESOURCE"),
    ("需求变更频繁影响交付节奏", "SCOPE"),
    ("技术方案选型存在不确定性", "TECHNICAL"),
    ("天气、政策等外部条件变化", "EXTERNAL"),
]

COST_SUBJECTS = ["工程建设费", "设备采购费", "软件与集成费", "咨询服务费",
                 "人工成本", "材料费", "监理费", "其他费用"]


def seed_milestones_costs_risks(db: Session, projects: list, wbs_cache: dict) -> None:
    for p in projects:
        span = max((p.planned_end_date - p.start_date).days, 30)
        for mi, (name, code, ratio) in enumerate(MILESTONE_TEMPLATE):
            planned = p.start_date + dt.timedelta(days=int(span * ratio))
            passed = planned <= TODAY
            achieved = passed and (p.progress / 100.0) >= ratio - 0.06
            ms = Milestone(
                project_id=p.id, milestone_code=code, milestone_name=name,
                plan_date=planned,
                actual_date=(planned + dt.timedelta(days=random.randint(-3, 12))
                             if achieved else None),
                status=("ACHIEVED" if achieved else
                        "DELAYED" if passed else "PENDING"),
                delay_days=(random.randint(3, 21) if (passed and not achieved) else 0),
                owner=pick([p.project_manager_name, "工程管理部", "项目管理办公室"], mi),
                deliverable=pick(["批复文件", "评审纪要", "开工报告", "阶段验收单",
                                  "调试报告", "验收证书", "结算书"], mi),
                is_key=(mi in (0, 5)),
                sort_order=mi,
            )
            db.add(ms)

        cats = random.sample(COST_SUBJECTS,
                             k=min(len(COST_SUBJECTS), random.randint(4, 6)))
        weights = [random.uniform(0.6, 1.8) for _ in cats]
        tw = sum(weights)
        for ci, cname in enumerate(cats):
            budget = round(p.budget * weights[ci] / tw, 2)
            actual = round(budget * min(p.progress / 100.0
                                        * random.uniform(0.85, 1.18), 1.4), 2)
            db.add(ProjectCost(
                project_id=p.id, cost_code=f"CS{p.id:03d}{ci + 1:02d}",
                cost_subject=cname, cost_type=random.choice(["BUDGET", "CONTRACT"]),
                budget_amount=budget, contract_amount=round(budget * random.uniform(0.8, 1.0), 2),
                purchase_amount=round(budget * random.uniform(0.5, 0.95), 2),
                planned_cost=round(budget * p.planned_progress / 100, 2),
                actual_amount=actual,
                paid_amount=round(actual * random.uniform(0.7, 0.98), 2),
                occur_date=TODAY, supplier=pick(["供应商A", "供应商B", "供应商C", None], ci),
                remark=LABEL,
            ))
        for k in range(12):
            mon = TODAY.replace(day=1) - dt.timedelta(days=30 * (11 - k))
            db.add(ProjectCost(
                project_id=p.id, cost_code=f"CS{p.id:03d}M{k:02d}",
                cost_subject="月度汇总", cost_type="ACTUAL",
                budget_amount=round(p.budget / 30, 2),
                planned_cost=round(p.budget / 30, 2),
                actual_amount=round(p.budget / 30 * random.uniform(0.7, 1.3), 2),
                paid_amount=round(p.budget / 36 * random.uniform(0.7, 1.2), 2),
                occur_date=mon, remark=LABEL,
            ))

        risks = random.sample(RISK_LIBRARY, k=min(random.randint(4, 8),
                                                  len(RISK_LIBRARY)))
        for ri, (rdesc, rcat) in enumerate(risks):
            prob = random.choices([1, 2, 3, 4, 5], weights=[15, 25, 30, 20, 10])[0]
            impact = random.choices([1, 2, 3, 4, 5], weights=[10, 20, 30, 25, 15])[0]
            score = prob * impact
            level = ("CRITICAL" if score >= 20 else "HIGH" if score >= 12
                     else "MEDIUM" if score >= 6 else "LOW")
            db.add(ProjectRisk(
                project_id=p.id, risk_code=f"RK{p.id:03d}{ri + 1:02d}",
                risk_title=pick(["进度风险", "成本风险", "质量风险", "安全风险",
                                 "采购风险", "合规风险", "资源风险", "需求风险",
                                 "技术风险", "外部风险"], ri),
                risk_description=rdesc, risk_category=rcat,
                probability=prob, impact=impact, risk_score=score, risk_level=level,
                risk_owner=pick([p.project_manager_name, "工程管理部",
                                 "采购部", "安全环保部"], ri),
                strategy=random.choice(["规避", "减轻", "转移", "接受"]),
                response_plan="建立专项跟踪机制，明确责任人与时间节点，按周复盘。",
                trigger_condition=pick(["进度偏差超过 5%", "成本偏差超过 3%",
                                        "外部条件发生变化", "关键人员变动"], ri),
                status=random.choice(["OPEN", "OPEN", "MITIGATING", "CLOSED"]),
                identified_date=TODAY - dt.timedelta(days=random.randint(10, 120)),
                due_date=TODAY + dt.timedelta(days=random.randint(7, 90)),
                ai_identified=random.random() < 0.45,
                related_wbs_code=None,
            ))

        for ii in range(random.randint(1, 4)):
            db.add(ProjectIssue(
                project_id=p.id, issue_code=f"IS{p.id:03d}{ii + 1:02d}",
                issue_title=pick(["现场签证办理滞后", "图纸会审意见未闭环",
                                  "接口联调不通过", "材料到场时间与计划不符",
                                  "施工界面移交未完成"], ii),
                issue_description="现场执行过程中发现的问题，已建立跟踪台账。",
                severity=random.choice(["HIGH", "MEDIUM", "MEDIUM", "LOW"]),
                owner=pick([p.project_manager_name, "工程管理部", "监理单位"], ii),
                raised_by=pick(["监理单位", "施工单位", "项目经理", "建设单位"], ii),
                raised_date=TODAY - dt.timedelta(days=random.randint(5, 80)),
                due_date=TODAY + dt.timedelta(days=random.randint(3, 45)),
                status=random.choice(["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"]),
                solution="已明确整改责任人与完成时限。" if random.random() < 0.5 else None,
            ))

        for ci in range(random.randint(1, 3)):
            new_end = p.planned_end_date + dt.timedelta(days=random.randint(-10, 30))
            db.add(ProjectChange(
                project_id=p.id, change_code=f"CR{p.id:03d}{ci + 1:02d}",
                change_title=pick(["增加部分智能化点位", "调整施工工序",
                                   "增加临时围挡及安全措施", "需求增补：新增报表导出",
                                   "材料品牌替代申请"], ci),
                change_type=random.choice(["SCOPE", "SCHEDULE", "COST", "TECHNICAL"]),
                change_reason="现场条件/业务需求变化，需相应调整范围与资源投入。",
                before_snapshot={"planned_end_date": p.planned_end_date.isoformat(),
                                 "budget": p.budget},
                after_snapshot={"planned_end_date": new_end.isoformat(),
                                "budget": round(p.budget * (1 + random.uniform(-0.02, 0.05)), 2)},
                impact_scope="影响范围：进度、成本、资源投入。",
                impact_schedule_days=random.randint(-10, 30),
                impact_cost=round(p.budget * random.uniform(0.005, 0.045), 2),
                impact_risk=random.choice(["LOW", "MEDIUM", "HIGH"]),
                ai_analysis="根据变更内容与影响面评估，建议按变更流程审批后执行。",
                applicant_name=pick([p.project_manager_name, "技术部", "工程管理部"], ci),
                apply_date=TODAY - dt.timedelta(days=random.randint(3, 90)),
                status=random.choice(["PENDING", "APPROVED", "APPROVED", "REJECTED"]),
                is_baseline_change=random.random() < 0.35,
                new_baseline_version=(f"V{random.randint(1, 3)}" if random.random() < 0.35
                                      else None),
            ))
    db.flush()


# ==========================================================================
# 9. 工单 / 设备 / 能耗 / 安全
# ==========================================================================
WO_TITLES = [
    ("空调不制冷", "报修"), ("照明灯管损坏", "报修"), ("水管漏水", "报修"),
    ("电梯异响", "维保"), ("门禁刷卡异常", "报修"), ("消防通道堆放杂物", "安保"),
    ("公共区域卫生投诉", "保洁"), ("绿化带枯死补种", "绿化"), ("空调滤网清洗", "维保"),
    ("电梯季度保养", "维保"), ("配电房巡检", "巡检"), ("水泵房巡检", "巡检"),
    ("卫生间漏水", "报修"), ("停车场道闸故障", "报修"), ("噪音投诉处理", "投诉"),
]


def seed_work_orders(db: Session, parks: list, buildings: list,
                     enterprises: list) -> int:
    assignees = ["张工程", "李物业", "王维修", "赵巡检", "陈安保", "刘保洁"]
    teams = ["工程部", "物业部", "安保部", "综合部", "外委单位"]
    n_total = 1400
    for i in range(n_total):
        park = random.choices(parks, weights=[0.4, 0.26, 0.2, 0.14])[0]
        bids = [b for b in buildings if b.park_id == park.id] or buildings
        bd = random.choice(bids)
        title, wtype = random.choice(WO_TITLES)
        submit = tm(random.randint(-180, 0), random.randint(8, 19), random.randint(0, 59))
        sev = random.choices(["LOW", "MEDIUM", "HIGH", "URGENT"],
                             weights=[35, 40, 18, 7])[0]
        sla = {"LOW": 24, "MEDIUM": 12, "HIGH": 6, "URGENT": 3}[sev]
        rnd = random.random()
        if rnd < 0.82:
            status = "CLOSED"
            handle = sla * random.uniform(0.25, 0.95)
            finish = submit + dt.timedelta(hours=handle)
            close = finish + dt.timedelta(hours=random.uniform(0.5, 6))
            timeout = handle > sla
        elif rnd < 0.92:
            status, finish, close = "PROCESSING", None, None
            timeout = (NOW - submit).total_seconds() / 3600 > sla
        else:
            status, finish, close = "SUBMITTED", None, None
            timeout = (NOW - submit).total_seconds() / 3600 > sla
        ent = random.choice(enterprises) if random.random() < 0.45 else None
        handle_hours = (round((finish - submit).total_seconds() / 3600, 2)
                        if finish else None)
        db.add(WorkOrder(
            order_code="WO" + submit.strftime("%y%m") + f"{i + 1:05d}",
            title=title, order_type=wtype, park_id=park.id, building_id=bd.id,
            space_id=None, location=bd.building_name + "·" + pick(
                ["1F 大堂", "3F 走道", "地下车库", "设备房", "屋面", "卫生间"], i),
            enterprise_id=ent.id if ent else None,
            enterprise_name=ent.enterprise_name if ent else None,
            description=bd.building_name + "发生「" + title + "」，已受理并派单。",
            ai_category=wtype,
            ai_confidence=round(random.uniform(0.72, 0.97), 3),
            ai_dispatch_suggestion="建议派单至" + random.choice(teams) + "处理。",
            priority=sev,
            sla_hours=sla, status=status,
            reporter_name=(ent.enterprise_name if ent else
                           pick(["物业巡检", "企业员工", "安保人员"], i)),
            reporter_phone="1" + random.choice("35789") + str(random.randint(10000000, 99999999)),
            assignee_name=random.choice(assignees),
            assignee_team=random.choice(teams),
            submit_at=submit,
            dispatch_at=submit + dt.timedelta(minutes=random.randint(2, 30)),
            accept_at=submit + dt.timedelta(minutes=random.randint(5, 120)),
            finish_at=finish, close_at=close,
            response_minutes=random.randint(4, 180),
            handle_hours=handle_hours,
            is_timeout=timeout,
            rating=(random.choice([3, 4, 4, 5, 5, 5]) if status == "CLOSED" else None),
            rating_comment=("处理及时，服务满意。" if random.random() < 0.85
                            else "响应速度一般。" if status == "CLOSED" else None),
            cost=round(random.uniform(0, 2400), 2) if status == "CLOSED" else 0,
        ))
    db.flush()
    return n_total


DEVICE_CATALOG = [
    ("电梯", "特种设备", (30, 400000)), ("中央空调主机", "暖通设备", (90, 860000)),
    ("冷水机组", "暖通设备", (90, 640000)), ("消防主机", "消防设备", (90, 320000)),
    ("视频监控", "安防设备", (365, 12000)), ("门禁控制器", "安防设备", (180, 8600)),
    ("配电柜", "供配电设备", (90, 128000)), ("变压器", "供配电设备", (180, 420000)),
    ("给水泵", "给排水设备", (90, 68000)), ("排污泵", "给排水设备", (90, 42000)),
    ("照明控制箱", "电气设备", (180, 16000)), ("光伏逆变器", "新能源设备", (365, 96000)),
    ("充电桩", "新能源设备", (180, 36000)), ("能效监测终端", "计量设备", (365, 8200)),
]

DEVICE_COUNTS = [420, 300, 220, 160]


def seed_devices(db: Session, parks: list, buildings: list) -> list:
    rows = []
    for idx, park in enumerate(parks):
        count = DEVICE_COUNTS[idx] if idx < len(DEVICE_COUNTS) else 150
        bids = [b for b in buildings if b.park_id == park.id] or buildings
        for i in range(count):
            bd = random.choice(bids)
            dtype, dcat, (cycle, price) = random.choice(DEVICE_CATALOG)
            health = random.uniform(55, 99)
            if random.random() < 0.12:
                health = random.uniform(22, 55)
            last_ins = TODAY - dt.timedelta(days=random.randint(1, 200))
            next_main = last_ins + dt.timedelta(days=cycle)
            status = "RUNNING"
            if health < 35:
                status = random.choice(["FAULT", "OFFLINE"])
            elif health < 55:
                status = random.choice(["RUNNING", "MAINTAINING"])
            bname = bd.building_name
            d_ = Device(
                device_code=f"DV{idx + 1:02d}{i + 1:05d}",
                device_name=bname + "-" + dtype + f"{i % 20 + 1:02d}",
                device_type=dtype, park_id=park.id, building_id=bd.id,
                floor_id=None,
                location=bname + "·" + pick(["B1", "1F", "3F", "6F", "屋面", "设备层"], i),
                brand=random.choice(["美的", "格力", "海尔", "西门子", "施耐德",
                                     "ABB", "海康威视", "大华", "国产品牌A", "国产品牌B"]),
                model=dtype[:2].upper() + "-" + str(random.randint(100, 9999)),
                serial_no="SN" + str(random.randint(10 ** 9, 10 ** 10 - 1)),
                owner_name=pick(["业主自有", "园区自持", "企业租用"], i),
                supplier=pick(["供应商A", "供应商B", "供应商C", "供应商D"], i),
                install_date=TODAY - dt.timedelta(days=random.randint(120, 2600)),
                warranty_end=TODAY + dt.timedelta(days=random.randint(-800, 900)),
                service_life_years=random.choice([8, 10, 10, 15, 20]),
                status=status,
                is_online=(status != "OFFLINE"),
                health_score=round(health, 1),
                inspect_cycle_days=cycle,
                last_inspect_date=last_ins,
                next_maintain_date=next_main,
                runtime_hours=random.randint(2000, 42000),
                energy_consumption=round(random.uniform(200, 48000), 2),
                fault_count=random.randint(0, 7 if health < 55 else 3),
                is_iot_connected=random.random() < 0.72,
                iot_protocol=random.choice(["MQTT", "Modbus", "BACnet", "OPC-UA", None]),
                purchase_price=round(price * random.uniform(0.85, 1.15), 2),
                remark=LABEL,
            )
            db.add(d_)
            rows.append(d_)
    db.flush()
    return rows


def seed_device_inspections(db: Session, devices: list) -> None:
    sample = random.sample(devices, k=min(700, len(devices)))
    for dv in sample:
        for k in range(random.randint(1, 3)):
            plan = dv.last_inspect_date - dt.timedelta(days=random.randint(0, 300))
            abnormal = random.random() < 0.14
            db.add(DeviceInspection(
                device_id=dv.id, park_id=dv.park_id,
                inspect_code=f"INS{dv.id:05d}{k + 1}",
                inspect_type=pick(["日常巡检", "月度保养", "季度检修", "专项检测"], k),
                plan_date=plan, actual_date=plan + dt.timedelta(days=random.randint(-1, 4)),
                inspector=pick(["张工程", "李物业", "赵巡检", "外委单位A"], k),
                result="ABNORMAL" if abnormal else "NORMAL",
                description=("巡检发现异常，已登记并跟进处理。" if abnormal else "巡检正常。"),
                fault_desc=("发现部件磨损/参数偏离正常范围。" if abnormal else None),
                solution=("已更换部件并复测合格。" if abnormal and random.random() < 0.6 else None),
                cost=round(random.uniform(0, 8600), 2) if abnormal else 0,
                next_plan_date=plan + dt.timedelta(days=dv.inspect_cycle_days),
                status="DONE",
            ))
    db.flush()


def seed_energy(db: Session, parks: list, buildings: list) -> None:
    for park in parks:
        for bd in [b for b in buildings if b.park_id == park.id]:
            base_elec = bd.build_area * random.uniform(42, 92)
            base_water = bd.build_area * random.uniform(0.7, 1.8)
            for m in range(24):
                mon = mon_back(23 - m)
                season = 1.0 + 0.34 * abs(((mon.month - 7) % 12) - 6) / 6.0
                adj = 1.28 if mon.month in (6, 7, 8, 12, 1) else 1.0
                elec = base_elec * season * adj * random.uniform(0.88, 1.12)
                water = base_water * random.uniform(0.85, 1.15) * (
                    1.1 if mon.month in (6, 7, 8) else 1.0)
                pe = random.uniform(0.62, 0.78)
                pw = random.uniform(3.4, 4.3)
                base_e = base_elec * season
                base_w = base_water
                db.add(EnergyRecord(
                    # energy_type 必须存规范枚举值（见 core/enums.py 的 EnergyType）。
                    # 早期这里写的是中文「电」/「水」，而所有消费方（dashboard_service /
                    # operation.py / space.py / agent tools）都按 "ELECTRICITY" 比较，
                    # 导致能源模块全部指标恒为 0。
                    park_id=park.id, building_id=bd.id, energy_type="ELECTRICITY",
                    record_date=mon, consumption=round(elec, 2), unit="kWh",
                    cost=round(elec * pe, 2), carbon_kg=round(elec * 0.581, 2),
                    baseline=round(base_e, 2),
                    is_anomaly=elec > base_e * adj * 1.09,
                    anomaly_ratio=round(elec / max(base_e * adj, 1), 4),
                    anomaly_note=("用电量显著高于基准，建议核查空调与照明运行策略。"
                                  if elec > base_e * adj * 1.09 else None),
                    is_demo=True,
                ))
                db.add(EnergyRecord(
                    park_id=park.id, building_id=bd.id, energy_type="WATER",
                    record_date=mon, consumption=round(water, 2), unit="m³",
                    cost=round(water * pw, 2), carbon_kg=round(water * 0.344, 2),
                    baseline=round(base_w, 2),
                    is_anomaly=water > base_w * 1.22,
                    anomaly_ratio=round(water / max(base_w, 1), 4),
                    anomaly_note=("用水量显著高于基准，建议检查管网是否存在漏损。"
                                  if water > base_w * 1.22 else None),
                    is_demo=True,
                ))
    db.flush()


HAZARD_LIBRARY = [
    ("消防通道被占用", "FIRE"), ("灭火器超期未检验", "FIRE"), ("消防栓被遮挡", "FIRE"),
    ("电线私拉乱接", "ELECTRIC"), ("配电箱未上锁", "ELECTRIC"), ("设备接地不良", "ELECTRIC"),
    ("高处作业未系安全带", "WORK_AT_HEIGHT"), ("脚手架搭设不规范", "WORK_AT_HEIGHT"),
    ("危化品未分类存放", "CHEMICAL"), ("有限空间作业无监护", "CONFINED_SPACE"),
    ("安全出口标识缺失", "FIRE"), ("员工未佩戴劳保用品", "PERSONAL"),
    ("叉车超速行驶", "EQUIPMENT"), ("施工区域未设置围挡", "CONSTRUCTION"),
    ("应急照明失效", "FIRE"), ("燃气管道未做泄漏检测", "GAS"),
]

INCIDENT_LIBRARY = [
    ("轻微滑倒受伤", "INJURY", "LOW"), ("货架倒塌未伤人", "EQUIPMENT", "MEDIUM"),
    ("配电箱短路冒烟", "FIRE", "HIGH"), ("叉车碰撞货物", "EQUIPMENT", "MEDIUM"),
    ("化学品微量泄漏", "CHEMICAL", "HIGH"), ("高处坠物未伤人", "WORK_AT_HEIGHT", "MEDIUM"),
    ("电梯困人", "EQUIPMENT", "HIGH"), ("水管爆裂造成积水", "FLOOD", "MEDIUM"),
    ("员工轻微烫伤", "INJURY", "LOW"), ("燃气报警器动作", "GAS", "HIGH"),
]


def seed_safety(db: Session, parks: list, buildings: list,
                enterprises: list) -> None:
    for park in parks:
        bids = [b for b in buildings if b.park_id == park.id]
        for i in range(random.randint(90, 150)):
            hz, cat = random.choice(HAZARD_LIBRARY)
            level = random.choices(["LOW", "MEDIUM", "HIGH", "CRITICAL"],
                                   weights=[40, 35, 18, 7])[0]
            found = TODAY - dt.timedelta(days=random.randint(0, 200))
            deadline = found + dt.timedelta(
                days={"LOW": 30, "MEDIUM": 15, "HIGH": 7, "CRITICAL": 3}[level])
            status = random.choices(["CLOSED", "RECTIFYING", "OPEN", "OVERDUE"],
                                    weights=[55, 22, 12, 11])[0]
            if status in ("OPEN", "RECTIFYING") and deadline < TODAY:
                status = "OVERDUE"
            db.add(SafetyHazard(
                hazard_code=f"HD{park.id:02d}{i + 1:04d}",
                park_id=park.id, hazard_type=cat, hazard_level=level,
                location=pick(["生产车间", "地下车库", "配电房", "公共走道",
                               "装卸区", "屋面", "仓库"], i),
                description="检查发现「" + hz + "」，要求限期整改。",
                source=pick(["日常巡检", "专项检查", "第三方检查", "企业自报", "AI 识别"], i),
                found_date=found,
                responsible_dept=pick(["物业部", "工程部", "企业安全负责人", "施工方"], i),
                rectify_deadline=deadline, status=status,
                risk_source_type=cat,
            ))
        for i in range(random.randint(5, 16)):
            title, cat, sev = random.choice(INCIDENT_LIBRARY)
            found = tm(random.randint(-200, 0), random.randint(6, 22), random.randint(0, 59))
            deadline = found + dt.timedelta(days=random.randint(3, 30))
            done = random.random() < 0.85
            db.add(SafetyIncident(
                incident_code=f"IN{park.id:02d}{i + 1:03d}",
                title=title, park_id=park.id,
                building_id=(random.choice(bids).id if bids else None),
                incident_type=cat, risk_level=sev, severity=sev,
                location=pick(["生产车间", "地下车库", "配电房", "公共走道",
                               "装卸区", "屋面"], i),
                description="园区发生「" + title + "」，已启动应急响应并完成处置。",
                source=pick(["监控发现", "人员上报", "报警系统", "巡查发现"], i),
                found_by=pick(["安保值班室", "企业负责人", "巡检员"], i),
                found_at=found,
                responsible_person=cn_name(i * 7 + 3),
                responsible_dept=pick(["物业部", "安全环保部", "工程部", "企业"], i),
                status="CLOSED" if done else "PROCESSING",
                reported_at=found + dt.timedelta(minutes=random.randint(5, 40)),
                assigned_at=found + dt.timedelta(minutes=random.randint(20, 120)),
                rectified_at=found + dt.timedelta(hours=random.randint(4, 240)) if done else None,
                reviewed_at=found + dt.timedelta(hours=random.randint(6, 300)) if done else None,
                closed_at=found + dt.timedelta(hours=random.randint(8, 360)) if done else None,
                rectify_deadline=deadline,
                rectify_measure="现场处置→原因调查→整改跟踪→举一反三排查。",
                review_result="复查通过。" if done else None,
                handle_hours=round(random.uniform(2, 160), 1) if done else None,
                is_overdue=(not done and deadline.date() < TODAY),
            ))
    db.flush()


# ==========================================================================
# 10. 政策 / 服务 / 活动 / 会议室 / 门禁
# ==========================================================================
# 政策库
#
# 第 9 项是**结构化申报条件**（写入 Policy.conditions，类型为 dict）。
# 键名必须与 app/agent/tools/__init__.py 的 _match_policy() 逐一对应，否则
# 该条件会被静默忽略——这正是「政策AI 永远返回数据不足」的历史成因。
#   industries / revenue_min,max（万元）/ employee_min,max / ip_min /
#   invention_patent_min / rnd_ratio_min / require_high_tech /
#   require_specialized / require_tech_sme / established_years_min
# ==========================================================================
POLICY_LIBRARY = [
    ("高新技术企业认定奖励", "科技奖励", "市级",
     "对首次通过高新技术企业认定的企业给予一次性奖励。",
     "高新技术企业证书、纳税证明", 300000, "2026-12-31",
     "企业需为独立法人且注册地在园区内；具体以主管部门最新口径为准。",
     {"industries": ["电子信息", "智能制造", "生物医药", "新能源", "软件与信息服务",
                     "新材料", "节能环保"],
      "require_high_tech": True, "established_years_min": 1, "ip_min": 1}),
    ("研发费用加计扣除", "税收优惠", "国家级",
     "企业研发费用按规定比例在税前加计扣除。",
     "研发费用辅助账、项目立项材料", 0, "2026-12-31",
     "享受比例与归集口径以税务主管部门规定为准。",
     {"rnd_ratio_min": 3, "established_years_min": 2, "revenue_min": 500}),
    ("专精特新中小企业奖励", "科技奖励", "省级",
     "对认定为专精特新中小企业的给予奖励。",
     "认定文件、财务审计报告", 500000, "2026-10-31", "需先取得省级认定资格。",
     {"require_specialized": True, "revenue_min": 1000, "rnd_ratio_min": 3,
      "ip_min": 5}),
    ("技改设备投资补贴", "产业扶持", "市级",
     "对企业技术改造设备投资给予一定比例补贴。",
     "设备采购合同、发票、验收单", 2000000, "2026-11-30",
     "补贴比例与上限以申报指南为准。",
     {"industries": ["智能制造", "新材料", "新能源"], "revenue_min": 2000,
      "employee_min": 50}),
    ("稳岗补贴", "人才与就业", "市级",
     "对不裁员少裁员的参保企业给予稳岗返还。",
     "社保缴纳证明、裁员率证明", 150000, "2026-09-30",
     "需满足失业保险参保及裁员率条件。",
     {"employee_min": 20, "revenue_min": 300}),
    ("人才安居补贴", "人才与就业", "区级",
     "对园区引进的高层次人才给予租房/购房补贴。",
     "人才认定文件、劳动合同、社保记录", 240000, "2026-12-15",
     "按人才层次分档，需在园区企业连续缴纳社保。",
     {"employee_min": 10, "revenue_min": 300}),
    ("首台（套）重大装备奖励", "科技奖励", "省级",
     "对首台（套）重大技术装备给予奖励。",
     "首台套认定文件、销售合同", 1000000, "2026-12-31", "需通过省级首台套认定。",
     {"industries": ["智能制造", "新材料"], "ip_min": 5, "invention_patent_min": 1}),
    ("绿色工厂奖励", "绿色低碳", "国家级",
     "对获评绿色工厂、绿色园区的给予奖励。",
     "评价报告、认定文件", 800000, "2026-12-31", "需通过第三方评价。",
     {"industries": ["节能环保", "新能源", "新材料"], "employee_min": 100}),
    ("知识产权贯标补贴", "知识产权", "市级",
     "对通过知识产权管理规范贯标认证的企业给予补贴。",
     "贯标认证证书", 100000, "2026-12-31", "需取得有效贯标认证。",
     {"ip_min": 3}),
    ("数字化改造服务券", "数字化", "市级",
     "面向中小企业发放数字化改造服务券，抵扣服务费用。",
     "企业营业执照、服务合同", 50000, "2026-12-31", "每家企业每年限领一次。",
     {"employee_max": 300, "revenue_max": 10000}),
    ("跨境电商扶持资金", "外贸扶持", "市级",
     "对跨境电商企业给予物流、平台费用补贴。",
     "跨境电商交易流水、平台入驻证明", 300000, "2026-11-15",
     "需具备跨境电商实际交易数据。",
     {"industries": ["现代物流", "软件与信息服务"], "revenue_min": 500}),
    ("上市挂牌奖励", "金融支持", "区级",
     "对完成股改、挂牌、上市的企业分阶段奖励。",
     "股改文件、挂牌/上市证明", 3000000, "2027-06-30", "按阶段分档奖励。",
     {"revenue_min": 5000, "established_years_min": 3}),
]

POLICY_INDUSTRIES = ["电子信息", "智能制造", "生物医药", "新能源", "软件与信息服务",
                     "新材料", "现代物流", "节能环保"]


def seed_policies(db: Session, enterprises: list) -> None:
    pols = []
    for i, row in enumerate(POLICY_LIBRARY):
        name, cat, level, desc, mat, amount, deadline, note, cond = row
        # 适用行业与匹配条件同源：政策列表页展示的"适用行业"就是匹配引擎实际使用的条件，
        # 避免"页面写着电子信息、匹配时却按别的行业算"这类数据自相矛盾。
        industries = cond.get("industries") or random.sample(POLICY_INDUSTRIES, k=4)
        p = Policy(
            policy_code=f"PO{i + 1:03d}", policy_name=name, policy_level=level,
            issuing_authority=pick(["市工业和信息化局", "省科学技术厅", "市发展改革委",
                                    "区经济发展局", "市人力资源局"], i),
            policy_category=cat,
            applicable_industry=industries,
            applicable_scale=random.choice(["不限", "中小微企业", "规上企业", "不限"]),
            conditions=dict(cond),
            subsidy_amount=float(amount),
            requirement="需按要求提交申报材料并通过主管部门审核。",
            material_list=mat,
            publish_date=TODAY - dt.timedelta(days=random.randint(30, 400)),
            deadline=dt.date(int(deadline[:4]), int(deadline[5:7]), int(deadline[8:10])),
            source_url=f"https://example.demo.gov.cn/policy/{i + 1:03d}",
            content=desc + "（" + note + "）",
            status="ACTIVE",
        )
        db.add(p)
        pols.append(p)
    db.flush()
    return pols


def scale_of(ent) -> str:
    """按从业人数推导企业规模（用于政策适用性判断）。"""
    n = ent.employee_count or 0
    if n >= 300:
        return "LARGE"
    if n >= 80:
        return "MEDIUM"
    if n >= 20:
        return "SMALL"
    return "MICRO"


def seed_policy_matches(db: Session, pols: list, enterprises: list) -> None:
    for ent in enterprises:
        if random.random() > 0.55:
            continue
        for pol in random.sample(pols, k=random.randint(1, 4)):
            industry_hit = ent.industry in (pol.applicable_industry or [])
            scale_hit = (pol.applicable_scale == "不限"
                         or (pol.applicable_scale == "规上企业"
                             and scale_of(ent) == "LARGE")
                         or (pol.applicable_scale == "中小微企业"
                             and scale_of(ent) != "LARGE"))
            if industry_hit and scale_hit:
                mtype, conf = "LIKELY_MATCH", random.uniform(0.68, 0.92)
            elif industry_hit or scale_hit:
                mtype, conf = "NEED_VERIFY", random.uniform(0.40, 0.65)
            else:
                mtype, conf = "DATA_INSUFFICIENT", random.uniform(0.15, 0.38)
            missing = []
            if not industry_hit:
                missing.append("行业确权证明")
            if not scale_hit:
                missing.append("企业规模/营收证明")
            db.add(PolicyMatch(
                policy_id=pol.id, enterprise_id=ent.id, park_id=ent.park_id,
                match_score=round(conf * 100, 1), match_level=mtype,
                match_reason=("行业「" + ent.industry + "」是否属于适用行业："
                              + ("是" if industry_hit else "否")
                              + "；企业规模「" + scale_of(ent) + "」是否符合「"
                              + (pol.applicable_scale or "不限") + "」："
                              + ("是" if scale_hit else "否") + "。"),
                missing_data=missing,
                risk_note=("材料齐备，建议尽快协助企业完成申报。"
                           if mtype == "LIKELY_MATCH" else
                           "材料存在缺口，申报前需人工复核，存在申报被驳回风险。"
                           if mtype == "NEED_VERIFY" else
                           "关键信息缺失，不得据此出具结论，请先补充企业基础信息。"),
                status=random.choice(["NEW", "FOLLOWING", "APPLIED", "CLOSED"]),
                matched_by="企业服务专员",
            ))
    db.flush()


SR_TYPES = ["工商注册协助", "政策申报辅导", "人才招聘服务", "融资对接",
            "法律咨询", "财税服务", "知识产权服务", "会议室预定支持"]


def seed_service_requests(db: Session, enterprises: list) -> None:
    for i in range(620):
        ent = random.choice(enterprises)
        st = random.choice(SR_TYPES)
        submit = tm(random.randint(-180, 0), random.randint(9, 18))
        status = random.choices(["CLOSED", "PROCESSING", "SUBMITTED", "REJECTED"],
                                weights=[62, 24, 10, 4])[0]
        db.add(ServiceRequest(
            request_code="SR" + submit.strftime("%y%m") + f"{i + 1:05d}",
            park_id=ent.park_id, enterprise_id=ent.id,
            enterprise_name=ent.enterprise_name,
            service_type=st, title=ent.enterprise_name + "申请" + st,
            content="企业提出「" + st + "」需求，请园区服务团队协助办理。",
            requirement="请安排专人对接口企业，并在承诺时限内反馈办理结果。",
            contact_person=ent.contact_person, contact_phone=ent.contact_phone,
            priority=random.choice(["HIGH", "MEDIUM", "MEDIUM", "LOW"]),
            status=status,
            handler=pick(["企业服务专员A", "企业服务专员B", "招商运营部"], i),
            handle_note=("已办结，企业确认满意。" if status == "CLOSED" else None),
            submit_at=submit,
            finish_at=(submit + dt.timedelta(days=random.randint(1, 20))
                       if status == "CLOSED" else None),
            satisfaction=random.choice([4, 5, 5, 5]) if status == "CLOSED" else None,
        ))
    db.flush()


def seed_activities_rooms(db: Session, parks: list, buildings: list,
                          enterprises: list) -> None:
    act_types = ["政策宣讲", "企业沙龙", "培训课程", "招聘会", "产品对接",
                 "党建活动", "安全生产培训"]
    for i in range(120):
        park = random.choice(parks)
        st = random.choice(act_types)
        sd = TODAY - dt.timedelta(days=random.randint(-60, 300))
        planned = random.randint(20, 200)
        bname = random.choice(buildings).building_name if buildings else "园区"
        start = dt.datetime.combine(sd, dt.time(9, 0))
        db.add(Activity(
            activity_code=f"AC{i + 1:04d}", park_id=park.id,
            title=st + "·" + random.choice(["2025 年第", "2026 年第"])
            + str(random.randint(1, 4)) + "期",
            activity_type=st,
            content="面向园区企业开展" + st + "，提升企业服务覆盖度。",
            start_time=start, end_time=start + dt.timedelta(hours=random.randint(2, 8)),
            location=bname + "会议中心",
            organizer=pick(["园区运营部", "企业服务部", "招商部", "政府合作部"], i),
            max_participants=planned,
            registered_count=int(planned * random.uniform(0.55, 1.15)),
            status="FINISHED" if sd < TODAY else "PLANNED",
        ))
    db.flush()

    rooms = []
    for park in parks:
        bids = [b for b in buildings if b.park_id == park.id] or buildings
        for r in range(6):
            rooms.append((park.id, bids[r % len(bids)].id,
                          "ABCDEF"[r] + " 会议室", random.choice([8, 12, 20, 40, 60])))
    for i in range(700):
        pid, bid, rname, cap = random.choice(rooms)
        day = TODAY + dt.timedelta(days=random.randint(-120, 20))
        start = dt.datetime.combine(day, dt.time(random.choice([9, 10, 13, 14, 15, 16]),
                                                  random.choice([0, 30])))
        ent = random.choice(enterprises) if random.random() < 0.6 else None
        db.add(MeetingRoomBooking(
            booking_code=f"MB{i + 1:05d}", park_id=pid, space_id=None,
            space_name=rname, enterprise_id=ent.id if ent else None,
            enterprise_name=ent.enterprise_name if ent else None,
            booker=(ent.enterprise_name if ent else
                    pick(["园区运营部", "招商部", "物业部"], i)),
            book_date=day, start_time=start,
            end_time=start + dt.timedelta(hours=random.randint(1, 3)),
            attendees=random.randint(3, cap),
            fee=round(random.uniform(0, 800), 2),
            status=random.choices(["FINISHED", "BOOKED", "CANCELLED"],
                                  weights=[60, 32, 8])[0],
        ))
    db.flush()


def seed_parking_vehicles_visitors(db: Session, parks: list,
                                   enterprises: list) -> None:
    spaces = db.query(ParkingSpace).all()
    for sp in spaces:
        plate = random.choice("苏苏苏浙浙皖沪粤") + random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") \
            + str(random.randint(10000, 99999))
        if sp.status == "OCCUPIED" and random.random() < 0.6:
            ent = random.choice([e for e in enterprises if e.park_id == sp.park_id]
                                or enterprises)
            db.add(Vehicle(
                plate_no=plate,
                vehicle_type=random.choices(["FUEL", "NEW_ENERGY"], weights=[62, 38])[0],
                owner_type="ENTERPRISE", enterprise_id=ent.id, park_id=sp.park_id,
                owner_name=ent.contact_person, phone=ent.contact_phone,
                card_type="MONTHLY", card_status="ACTIVE",
                valid_from=TODAY - dt.timedelta(days=random.randint(30, 400)),
                valid_to=TODAY + dt.timedelta(days=random.randint(-40, 330)),
                parking_space_id=sp.id,
            ))
        elif random.random() < 0.2:
            db.add(Vehicle(
                plate_no=plate, vehicle_type="FUEL", owner_type="VISITOR",
                park_id=sp.park_id, owner_name=cn_name(len(plate) * 7),
                card_type="TEMPORARY", card_status="ACTIVE",
                valid_from=TODAY - dt.timedelta(days=random.randint(1, 60)),
                valid_to=TODAY + dt.timedelta(days=random.randint(1, 30)),
            ))
    db.flush()

    purposes = ["业务洽谈", "面试应聘", "设备维修", "货物配送", "参观考察", "会议", "培训"]
    for i in range(760):
        park = random.choice(parks)
        pool = [e for e in enterprises if e.park_id == park.id] or enterprises
        ent = random.choice(pool)
        vin = tm(random.randint(-60, 0), random.randint(8, 19), random.randint(0, 59))
        out = vin + dt.timedelta(hours=random.uniform(0.5, 9)) if random.random() < 0.9 else None
        db.add(Visitor(
            visit_code=f"VS{i + 1:05d}", park_id=park.id,
            visitor_name=random.choice(["王先生", "李女士", "张先生",
                                        "刘女士", "陈先生", "赵女士"]),
            phone="1" + random.choice("35789") + str(random.randint(100000000, 999999999)),
            id_card_mask="3201**********" + str(random.randint(1000, 9999)),
            company=random.choice(["某某科技有限公司", "某某供应链", "某某咨询",
                                   "某某设备供应商", "某某检测机构"]),
            visit_purpose=random.choice(purposes),
            visit_enterprise_id=ent.id, visit_enterprise_name=ent.enterprise_name,
            visit_person=ent.contact_person,
            visit_time=vin, leave_time=out,
            plate_no=random.choice(["", "", "苏A" + str(random.randint(10000, 99999))]),
            status="LEFT" if out else "IN",
            approver=pick(["前台", "企业对接人", "安保值班"], i),
        ))
        if random.random() < 0.7:
            db.add(AccessRecord(
                park_id=park.id,
                access_type=random.choice(["PERSON_QR", "FACE", "CARD", "PLATE"]),
                gate_name=random.choice(["南门", "北门", "地下车库", "东门"]) + "闸机",
                subject_name=random.choice(["王先生", "李女士", "张先生", "员工A", "员工B"]),
                plate_no=None, direction="IN", access_time=vin,
                device_code="AC" + str(random.randint(1000, 9999)), result="PASS",
            ))
    db.flush()


# ==========================================================================
# 11. 用户 / 角色分配
# ==========================================================================
USER_DEFS = [
    ("admin", "系统管理员", "SUPER_ADMIN", "信息技术部", "系统管理员", "GROUP", None),
    ("gm", "集团总经理", "GROUP_ADMIN", "集团办", "总经理", "GROUP", None),
    ("gm_ops", "集团运营总监", "GROUP_ADMIN", "集团运营中心", "运营总监", "GROUP", None),
    ("gm_finance", "集团财务总监", "FINANCE_STAFF", "集团财务部", "财务总监", "GROUP", None),
    ("p1_manager", "园区总经理·星海", "PARK_MANAGER", "星海园区办", "园区总经理", "PARK", 0),
    ("p2_manager", "园区总经理·临港", "PARK_MANAGER", "临港园区办", "园区总经理", "PARK", 1),
    ("p3_manager", "园区总经理·云谷", "PARK_MANAGER", "云谷园区办", "园区总经理", "PARK", 2),
    ("p4_manager", "园区总经理·滨水", "PARK_MANAGER", "滨水园区办", "园区总经理", "PARK", 3),
    ("p1_leasing", "招商主管·星海", "LEASING_MANAGER", "招商部", "招商主管", "PARK", 0),
    ("p2_leasing", "招商主管·临港", "LEASING_MANAGER", "招商部", "招商主管", "PARK", 1),
    ("p3_leasing", "招商专员·云谷", "LEASING_STAFF", "招商部", "招商专员", "PARK", 2),
    ("p1_pm", "项目经理·A栋改造", "PROJECT_MANAGER", "工程管理部", "项目经理", "PROJECT", 0),
    ("p2_pm", "项目经理·3#厂房", "PROJECT_MANAGER", "工程管理部", "项目经理", "PROJECT", 1),
    ("pm_digital", "项目经理·数字化平台", "PROJECT_MANAGER", "数字化部", "项目经理", "PROJECT", 0),
    ("finance1", "会计·星海", "FINANCE_STAFF", "财务部", "会计", "PARK", 0),
    ("finance2", "会计·临港", "FINANCE_STAFF", "财务部", "会计", "PARK", 1),
    ("prop1", "物业主管·星海", "PROPERTY_STAFF", "物业部", "物业主管", "PARK", 0),
    ("prop2", "物业主管·临港", "PROPERTY_STAFF", "物业部", "物业主管", "PARK", 1),
    ("prop3", "物业主管·云谷", "PROPERTY_STAFF", "物业部", "物业主管", "PARK", 2),
    ("eng1", "工程主管·星海", "OPERATION_STAFF", "工程部", "工程主管", "PARK", 0),
    ("energy1", "能源管理员", "OPERATION_STAFF", "能源管理部", "能源管理员", "PARK", 0),
    ("safety1", "安全主管·星海", "SAFETY_STAFF", "安全环保部", "安全主管", "PARK", 0),
    ("safety2", "安全主管·临港", "SAFETY_STAFF", "安全环保部", "安全主管", "PARK", 1),
    ("svc1", "企业服务专员·星海", "OPERATION_STAFF", "企业服务部", "服务专员", "PARK", 0),
    ("svc2", "企业服务专员·临港", "OPERATION_STAFF", "企业服务部", "服务专员", "PARK", 1),
    ("analyst", "数据分析师", "VIEWER", "数据中心", "数据分析师", "GROUP", None),
    ("auditor", "审计员", "VIEWER", "审计监察部", "审计员", "GROUP", None),
    ("tenant1", "企业用户·示例", "ENTERPRISE_ADMIN", "企业", "企业管理员", "ENTERPRISE", 0),
    ("park_staff", "园区综合专员", "OPERATION_STAFF", "园区综合部", "综合专员", "PARK", 0),
]


def seed_enterprise_bindings(db: Session, users: list, enterprises: list) -> int:
    """把 ENTERPRISE 数据范围的账号绑定到其所属企业。

    为什么必须有这一步：企业管理员的数据范围就是"本企业"，`users.enterprise_id`
    是唯一的归属依据。早期播种漏了它，于是企业管理员虽然角色是 ENTERPRISE 范围，
    系统却算不出"自己是谁家的"，范围过滤退化成园区级——实测能看到全园区
    128 家企业、1.3 万条账单。**没有归属主体的数据范围等于没有范围。**

    绑定规则：取该账号所在园区下企业编号最小的那家（确定性，便于复现）。
    """
    by_username = {u.username: u for u in users}
    first_of_park: dict[int, object] = {}
    for e in sorted(enterprises, key=lambda x: x.id):
        first_of_park.setdefault(e.park_id, e)

    bound = 0
    for username, _name, _rk, _dept, _title, scope, _pidx in USER_DEFS:
        if scope != "ENTERPRISE":
            continue
        u = by_username.get(username)
        if u is None or u.enterprise_id:
            continue
        ent = first_of_park.get(u.park_id)
        if ent is None:
            continue
        u.enterprise_id = ent.id
        bound += 1
    db.flush()
    return bound


def seed_users(db: Session, parks: list, roles: dict) -> tuple:
    users, users_by_park = [], {p.id: [] for p in parks}
    for username, name, role_key, dept, title, scope, pidx in USER_DEFS:
        if scope == "GROUP":
            park_scopes = [p.id for p in parks]
        elif pidx is not None and pidx < len(parks):
            park_scopes = [parks[pidx].id]
        else:
            park_scopes = []
        u = User(
            username=username,
            password_hash=hash_password("Park@2026"),
            real_name=name, email=username + "@smartpark.demo",
            phone="139" + str(random.randint(10000000, 99999999)),
            organization_id=None,
            park_id=(parks[pidx].id if pidx is not None and pidx < len(parks) else None),
            department=dept, position=title, status="ACTIVE",
            last_login_at=tm(random.randint(-14, 0), random.randint(8, 20)),
            is_demo=True, remark=LABEL,
        )
        db.add(u)
        db.flush()
        r = roles.get(role_key)
        if r:
            db.add(UserRole(user_id=u.id, role_id=r.id))
        for pid in park_scopes:
            db.add(UserParkScope(user_id=u.id, park_id=pid))
            users_by_park[pid].append(u)
        users.append(u)
    db.flush()
    return users, users_by_park


# ==========================================================================
# 12. AI / 审批 / 通知 / 审计 / 报表
# ==========================================================================
AI_QUESTIONS = [
    ("城东园区当前整体经营情况怎么样？", "operations"),
    ("A栋厂房改造工程进度是否正常？还有多久能完工？", "project"),
    ("哪些企业合同即将到期，需要提前续约？", "contract"),
    ("本月租金收缴情况如何，哪些企业存在欠费风险？", "finance"),
    ("园区当前招商漏斗转化率是多少，哪一环流失最多？", "leasing"),
    ("今天有哪些需要我关注的风险？", "operations"),
    ("3#定制厂房建设成本是否超预算？", "project"),
    ("园区能耗有没有异常，哪些楼宇用电偏高？", "energy"),
    ("有哪些企业可能符合高新技术企业认定奖励？", "policy"),
    ("当前未闭环的安全隐患有哪些，整改是否超期？", "safety"),
    ("物业工单超时率是多少，主要卡在哪个环节？", "property"),
    ("已租空间的空置风险有哪些？", "space"),
    ("智慧园区平台项目的敏捷迭代速度如何？", "project"),
    ("集团层面四个园区的经营指标对比如何？", "operations"),
    ("哪些设备健康度较低，需要安排计划性检修？", "energy"),
    ("园区入驻企业按行业分布情况如何？", "enterprise"),
]


def seed_ai_data(db: Session, users: list, parks: list) -> None:
    biz = [u for u in users if u.username not in ("tenant1", "auditor")]
    for i in range(180):
        u = random.choice(biz)
        q, key = random.choice(AI_QUESTIONS)
        created = tm(random.randint(-60, 0), random.randint(8, 20), random.randint(0, 59))
        conv = AIConversation(
            conversation_code=f"CV{i + 1:06d}", user_id=u.id,
            title=q[:26], park_id=u.park_id, agent_key="master",
            message_count=random.randint(2, 6),
            last_message_at=created + dt.timedelta(minutes=random.randint(1, 40)),
        )
        db.add(conv)
        db.flush()
        db.add(AIMessage(
            conversation_id=conv.id, role="user", content=q,
            agent_key="master", agent_name="园智AI总管",
            permission_level="L1", data_sufficient=True,
        ))
        db.add(AIMessage(
            conversation_id=conv.id, role="assistant",
            content=("【结论】本次回答基于平台数据库实时计算得出，"
                     "并附数据依据与计算口径。\n"
                     "【关键数据】详见证据链中的表名、记录数与筛选条件。\n"
                     "【原因分析】结合业务规则与历史数据对比分析。\n"
                     "【建议措施】建议按业务流程跟进处理。\n"
                     "【影响范围】涉及相关业务模块。\n"
                     "【风险】如未及时处理可能累积风险。\n"
                     "【责任部门/角色】由对应业务部门负责。\n"
                     "【决策状态】AI建议。"),
            agent_key=key, agent_name=key + " Agent",
            intent=key,
            structured={"conclusion": "已基于数据库实时数据完成分析",
                        "key_data": {}, "cause": "", "suggestion": "",
                        "impact": "", "risk": "", "owner": ""},
            evidence={"source": "数据库实时查询",
                      "tables": ["contract", "bill", "project", "enterprise"],
                      "record_count": random.randint(20, 3200),
                      "filters": {"park_id": u.park_id},
                      "formula": "由业务口径计算",
                      "note": LABEL},
            permission_level=random.choice(["L1", "L2", "L2"]),
            decision_status=random.choice(["信息提示", "AI建议", "需人工确认"]),
            tokens=random.randint(600, 3200),
            latency_ms=random.randint(320, 3600),
            data_sufficient=True,
        ))
    db.flush()

    recs = [
        ("contract", "CONTRACT_EXPIRY", "合同到期集中预警",
         "未来 90 天内有多份合同到期，建议提前启动续约沟通。", "WARNING", "/contracts"),
        ("finance", "RENT_ARREARS", "欠费催收建议",
         "存在账龄超过 90 天的应收账款，建议分级催收。", "CRITICAL", "/finance"),
        ("project", "PROJECT_DELAY", "关键路径延期预警",
         "关键路径任务出现延期，建议评估赶工或调整基线。", "CRITICAL", "/projects"),
        ("energy", "ENERGY_ANOMALY", "能耗异常提醒",
         "部分楼宇单位面积能耗高于同类水平，建议开展节能诊断。", "WARNING", "/energy"),
        ("safety", "SAFETY_HAZARD", "隐患整改超期提醒",
         "存在整改超期隐患，建议挂牌督办。", "CRITICAL", "/safety"),
        ("leasing", "LEASING_STAGNANT", "招商线索跟进提醒",
         "多条线索超过 7 天未跟进，建议重新分配。", "WARNING", "/leasing"),
        ("space", "SPACE_VACANT", "空置空间盘活建议",
         "连续空置超过 90 天的空间建议调整定价策略。", "WARNING", "/spaces"),
        ("device", "DEVICE_FAULT", "设备维保计划提醒",
         "部分设备健康度下降，建议纳入计划性检修。", "WARNING", "/devices"),
        ("service", "POLICY_DEADLINE", "政策申报窗口提醒",
         "临近申报截止日，建议提醒符合条件企业。", "INFO", "/policies"),
        ("property", "WORK_ORDER_TIMEOUT", "工单超时集中问题",
         "某类工单超时率偏高，建议优化派单规则。", "WARNING", "/work-orders"),
        ("budget", "BUDGET_OVERSPEND", "预算超支预警",
         "部分项目实际成本已接近或超过预算，建议复核。", "CRITICAL", "/projects"),
        ("device", "INSPECTION_OVERDUE", "巡检逾期提醒",
         "存在巡检逾期的设备，建议立即安排巡检。", "WARNING", "/devices"),
    ]
    for i, (mod, ntype, title, summary, sev, route) in enumerate(recs):
        for _ in range(random.randint(2, 4)):
            park = random.choice(parks)
            st = random.choice(["PENDING", "PENDING", "ADOPTED", "IGNORED",
                                "CONVERTED", "HANDLED"])
            db.add(AIRecommendation(
                rec_code=f"RC{i + 1:03d}{random.randint(100, 999)}",
                park_id=park.id, agent_key=mod, category=ntype,
                title=title, summary=summary,
                detail=(summary + " 数据来源：平台数据库实时计算（表："
                        + mod + " 相关业务表），统计口径与筛选条件见证据链。"),
                severity=sev, confidence=round(random.uniform(0.66, 0.95), 3),
                related_module=mod, related_object_type=mod,
                related_object_id=random.randint(1, 900),
                evidence={"source": "数据库实时计算", "record_count": random.randint(5, 480),
                          "note": LABEL},
                suggestion="建议由" + pick(["园区运营部", "财务部", "工程管理部",
                                            "物业部", "安全环保部"], i) + "跟进处理。",
                action_label="查看明细", action_route=route,
                permission_level=random.choice(["L1", "L2"]),
                decision_status=random.choice(["AI建议", "需人工确认"]),
                status=st,
                generated_date=TODAY - dt.timedelta(days=random.randint(0, 20)),
                read_count=random.randint(0, 42),
            ))
    db.flush()


def seed_approvals(db: Session, users: list, projects: list,
                   enterprises: list) -> None:
    types = [
        ("PROJECT_CHANGE", "项目变更申请", "L3"),
        ("CONTRACT_RENEWAL", "合同续约申请", "L3"),
        ("BUDGET_ADJUST", "预算调整申请", "L3"),
        ("AI_ACTION", "AI 建议执行确认", "L3"),
        ("SPACE_DISCOUNT", "空间租金优惠申请", "L3"),
        ("PURCHASE", "采购申请", "L3"),
        ("EXPENSE", "费用报销", "L2"),
        ("OVERTIME", "加班申请", "L1"),
    ]
    approvers = [("部门负责人", "PARK_STAFF"), ("园区总经理", "PARK_MANAGER"),
                 ("集团财务总监", "FINANCE_DIRECTOR"), ("集团总经理", "GROUP_EXEC")]
    for i in range(240):
        ctype, ctitle, level = random.choice(types)
        requester = random.choice(users)
        created = tm(random.randint(-90, 0), random.randint(8, 20))
        status = random.choices(["APPROVED", "PENDING", "IN_REVIEW",
                                 "REJECTED", "WITHDRAWN"],
                                weights=[52, 22, 8, 13, 5])[0]
        steps_total = random.randint(1, 4)
        cur_step = (steps_total if status == "APPROVED" else
                    random.randint(1, steps_total) if status in ("PENDING", "IN_REVIEW")
                    else steps_total)
        pid = random.choice(projects).id if projects and random.random() < 0.6 else None
        eid = (random.choice(enterprises).id
               if enterprises and random.random() < 0.4 else None)
        ar = ApprovalRequest(
            approval_code="AP" + created.strftime("%y%m") + f"{i + 1:05d}",
            approval_type=ctype, title=ctitle,
            park_id=requester.park_id,
            related_object_type=ctype, related_object_id=random.randint(1, 900),
            enterprise_id=eid, project_id=pid,
            amount=round(random.uniform(5000, 2600000), 2) if random.random() < 0.7 else None,
            content="基于业务需要提交审批，附相关依据材料与影响分析。",
            ai_analysis=("AI 评估：该申请涉及金额与影响范围已核对，"
                         + ("建议谨慎审批并补充材料。" if random.random() < 0.3
                            else "材料完整，可按流程审批。")),
            risk_level=random.choice(["LOW", "MEDIUM", "MEDIUM", "HIGH"]),
            urgency=random.choice(["NORMAL", "NORMAL", "URGENT"]),
            status=status,
            current_step=cur_step, total_steps=steps_total,
            applicant_id=requester.id, applicant_name=requester.real_name,
            apply_at=created,
            finish_at=(created + dt.timedelta(days=random.randint(1, 12))
                       if status in ("APPROVED", "REJECTED") else None),
            is_ai_generated=(ctype == "AI_ACTION"),
            source="AI_AGENT" if ctype == "AI_ACTION" else "WEB",
        )
        db.add(ar)
        db.flush()
        for s in range(steps_total):
            if status == "APPROVED":
                sstatus = "APPROVED"
            elif status == "REJECTED":
                sstatus = "REJECTED" if s == cur_step - 1 else "APPROVED"
            elif status in ("PENDING", "IN_REVIEW"):
                sstatus = ("APPROVED" if s < cur_step - 1 else
                           "PENDING" if s == cur_step - 1 else "WAITING")
            else:
                sstatus = "SKIPPED"
            name, role = approvers[min(s, len(approvers) - 1)]
            db.add(ApprovalStep(
                approval_id=ar.id, step_no=s + 1, step_name=name,
                approver_role=role, approver_name=cn_name(i * 3 + s * 7 + 5),
                status=sstatus,
                comment=("同意，按方案执行。" if sstatus == "APPROVED" else
                         "驳回：材料不齐，请补充后重新提交。" if sstatus == "REJECTED"
                         else None),
                approve_at=(created + dt.timedelta(hours=random.randint(2, 72))
                            if sstatus in ("APPROVED", "REJECTED") else None),
                duration_hours=(round(random.uniform(0.5, 60), 1)
                                if sstatus in ("APPROVED", "REJECTED") else None),
            ))
        ar.current_step = cur_step
        ar.total_steps = steps_total
    db.flush()


NOTICE_TEMPLATES = [
    ("CONTRACT_EXPIRY", "合同到期预警",
     "有合同将在 90 天内到期，请及时安排续约沟通。", "WARNING", "/contracts"),
    ("RENT_ARREARS", "账单逾期提醒",
     "存在已逾期未收账单，请跟进催收。", "CRITICAL", "/finance"),
    ("PROJECT_DELAY", "项目进度预警",
     "关键路径任务出现延期，请评估影响并及时纠偏。", "CRITICAL", "/projects"),
    ("BUDGET_OVERSPEND", "预算超支预警",
     "项目实际成本已接近或超过预算，请复核。", "CRITICAL", "/projects"),
    ("WORK_ORDER_TIMEOUT", "工单超时提醒",
     "存在超时未闭环工单，请尽快处理。", "WARNING", "/work-orders"),
    ("SAFETY_HAZARD", "安全隐患提醒",
     "存在超期未整改隐患，请挂牌督办。", "CRITICAL", "/safety"),
    ("ENERGY_ANOMALY", "能耗异常提醒",
     "楼宇能耗显著高于基准值，请排查原因。", "WARNING", "/energy"),
    ("DEVICE_FAULT", "设备故障提醒",
     "设备健康度偏低或已故障，请安排检修。", "WARNING", "/devices"),
    ("INSPECTION_OVERDUE", "巡检逾期提醒",
     "存在巡检逾期设备，请立即安排巡检。", "WARNING", "/devices"),
    ("SPACE_VACANT", "空间空置提醒",
     "存在长期空置空间，建议调整招商策略。", "WARNING", "/spaces"),
    ("LEASING_STAGNANT", "招商停滞预警",
     "线索长时间未跟进，建议重新分配。", "WARNING", "/leasing"),
    ("POLICY_DEADLINE", "政策申报提醒",
     "政策申报临近截止，请提醒相关企业。", "INFO", "/policies"),
    ("APPROVAL_PENDING", "待办审批提醒",
     "您有审批事项待处理。", "INFO", "/approvals"),
]


def seed_notifications(db: Session, users: list) -> None:
    for i in range(1000):
        ntype, title, content, sev, route = random.choice(NOTICE_TEMPLATES)
        u = random.choice(users)
        occurred = tm(random.randint(-30, 0), random.randint(8, 21), random.randint(0, 59))
        db.add(Notification(
            notice_code=f"NT{i + 1:06d}", notice_type=ntype, title=title,
            content=content, park_id=u.park_id, severity=sev,
            related_module=route.strip("/"), related_object_type=None,
            related_object_id=random.randint(1, 900),
            related_object_name=title, trigger_value=str(random.randint(1, 120)),
            threshold=str(random.randint(1, 30)),
            suggestion="建议按业务流程及时处理，避免风险累积。",
            action_label="查看详情", action_route=route,
            target_roles=None, target_user_id=u.id,
            is_read=random.random() < 0.55,
            is_handled=random.random() < 0.35,
            occurred_at=occurred,
            deadline=occurred + dt.timedelta(days=random.randint(1, 15)),
        ))
    db.flush()


AUDIT_ACTIONS = [
    ("auth", "LOGIN", "用户登录系统"),
    ("auth", "LOGOUT", "用户退出系统"),
    ("project", "EDIT", "修改项目基础信息"),
    ("project", "VIEW", "查看项目详情"),
    ("contract", "ADD", "新增合同记录"),
    ("contract", "EDIT", "修改合同条款"),
    ("finance", "EXPORT", "导出账单明细"),
    ("enterprise", "IMPORT", "批量导入企业档案"),
    ("space", "EDIT", "调整空间状态"),
    ("approval", "APPROVE", "审批通过申请"),
    ("agent", "AI", "调用 AI 智能体查询"),
    ("report", "EXPORT", "导出分析报表"),
    ("system", "CONFIG", "修改角色权限配置"),
    ("property", "EDIT", "变更工单状态"),
    ("energy", "VIEW", "查看能耗分析"),
    ("safety", "EDIT", "登记安全隐患"),
]


def seed_audit_logs(db: Session, users: list) -> None:
    for i in range(2400):
        mod, action, detail = random.choice(AUDIT_ACTIONS)
        u = random.choice(users)
        created = tm(random.randint(-90, 0), random.randint(7, 23), random.randint(0, 59))
        created = created.replace(second=random.randint(0, 59))
        db.add(AuditLog(
            log_code=f"LG{i + 1:07d}",
            user_id=u.id, username=u.username, real_name=u.real_name,
            park_id=u.park_id, module=mod, action=action,
            object_type=mod, object_id=random.randint(1, 5000),
            object_name=detail,
            before_value=None,
            after_value=({"status": "UPDATED", "note": LABEL}
                         if action in ("EDIT", "APPROVE", "CONFIG") else None),
            change_summary=detail,
            approval_info=None,
            source="AI" if action == "AI" else "WEB",
            ip_address="10." + str(random.randint(0, 255)) + "."
            + str(random.randint(0, 255)) + "." + str(random.randint(1, 254)),
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            result="SUCCESS" if random.random() < 0.97 else "FAILED",
            created_at=created,
        ))
    db.flush()


def seed_reports(db: Session, users: list, parks: list, projects: list) -> None:
    kinds = [
        ("园区经营月报", "OPERATING", "MONTHLY"),
        ("项目周报", "PROJECT", "WEEKLY"),
        ("项目风险报告", "PROJECT_RISK", "ADHOC"),
        ("招商分析报告", "LEASING", "MONTHLY"),
        ("财务分析报告", "FINANCE", "MONTHLY"),
        ("能耗分析报告", "ENERGY", "MONTHLY"),
        ("安全月报", "SAFETY", "MONTHLY"),
        ("物业服务报告", "PROPERTY", "MONTHLY"),
        ("集团经营季报", "GROUP", "QUARTERLY"),
        ("项目复盘报告", "PROJECT_REVIEW", "ADHOC"),
    ]
    for i in range(160):
        name, rtype, cycle = random.choice(kinds)
        park = random.choice(parks)
        pid = (random.choice(projects).id
               if rtype.startswith("PROJECT") and projects else None)
        u = random.choice(users)
        period = f"{TODAY.year}-{random.randint(1, 12):02d}"
        db.add(ReportRecord(
            report_code=f"RP{i + 1:05d}", report_name=name, report_type=rtype,
            park_id=park.id, project_id=pid, period=period,
            format=random.choice(["PDF", "EXCEL", "HTML"]),
            generated_by=u.real_name,
            content={"summary": "报告内容基于平台数据库实时计算生成。",
                     "sections": ["结论", "关键数据", "原因分析", "建议措施"],
                     "note": LABEL},
            file_path=None,
            status=random.choice(["DONE", "DONE", "DONE", "GENERATING", "FAILED"]),
        ))
    db.flush()


# ==========================================================================
# 主入口
# ==========================================================================
def refresh_project_milestone_counters(db: Session) -> int:
    """把 projects.milestone_total / milestone_done 与 milestones 表对齐。

    这两列是冗余缓存。历史实现只读不写，导致全库恒为 0（曾让三处
    「里程碑完成率」显示 0%）。读取方现已改为直接聚合 milestones 表，
    本函数保证缓存列不再与源表矛盾。
    """
    from sqlalchemy import func, select

    from app.models import Milestone, Project
    from app.services.project_engine import MILESTONE_DONE_STATUSES

    rows = db.execute(
        select(Milestone.project_id, Milestone.status, func.count())
        .group_by(Milestone.project_id, Milestone.status)
    ).all()
    stats: dict[int, list[int]] = {}
    for pid, status, cnt in rows:
        s = stats.setdefault(pid, [0, 0])
        s[0] += int(cnt)
        if status in MILESTONE_DONE_STATUSES:
            s[1] += int(cnt)

    n = 0
    for p in db.scalars(select(Project)).all():
        total, done = stats.get(p.id, [0, 0])
        if p.milestone_total != total or p.milestone_done != done:
            p.milestone_total, p.milestone_done = total, done
            n += 1
    return n


def main() -> None:
    t0 = dt.datetime.now()
    print("=" * 76)
    print("  园智汇 · AI产业园区智慧运营管理平台 —— 演示数据生成")
    print("=" * 76)

    Base.metadata.create_all(bind=engine)
    print("  数据表结构已就绪。")

    db = SessionLocal()
    try:
        clear_all(db)
        print("  已清空历史业务数据。")

        perms = seed_permissions(db)
        roles = seed_roles(db, perms)
        templates = seed_templates(db)
        orgs = seed_organizations(db)
        parks = seed_parks(db, templates, orgs)
        print(f"[1/12] 组织/权限/角色/模板  组织 {len(orgs)}，园区 {len(parks)}，"
              f"角色 {len(roles)}，权限 {len(perms)}")

        users, users_by_park = seed_users(db, parks, roles)
        print(f"[2/12] 用户与角色          用户 {len(users)}")

        buildings, floors, park_spaces = seed_buildings(db, parks)
        n_spaces = sum(len(v) for v in park_spaces.values())
        print(f"[3/12] 楼宇/楼层/空间      楼宇 {len(buildings)}，楼层 {len(floors)}，"
              f"空间 {n_spaces}")

        seed_parking(db, parks)
        print("[4/12] 停车位              完成")

        enterprises = seed_enterprises(db, parks)
        assign_spaces(db, parks, enterprises, park_spaces)
        seed_enterprise_contacts_tags(db, enterprises)
        bound = seed_enterprise_bindings(db, users, enterprises)
        print(f"[5/12] 企业与空间分配      企业 {len(enterprises)}，企业账号绑定 {bound}")

        channels, _ = seed_channels_activities(db, parks)
        leads = seed_leads(db, parks, channels, users_by_park)
        print(f"[6/12] 招商渠道与线索      渠道 {len(channels)}，线索 {len(leads)}")

        contracts_meta = seed_contracts(db, parks, enterprises, park_spaces,
                                        users_by_park)
        db.flush()
        print(f"[7/12] 合同                合同 {len(contracts_meta)}")

        seed_bills(db, contracts_meta, [])
        n_bills = db.query(func.count()).select_from(Bill).scalar()
        print(f"[8/12] 账单                账单 {n_bills}")

        projects, agile_map, hp, sub = seed_projects(db, parks, users_by_park)
        wbs_cache = seed_phases_wbs(db, projects, agile_map)
        seed_milestones_costs_risks(db, projects, wbs_cache)
        n_wbs = sum(len(v) for v in wbs_cache.values())
        print(f"[9/12] 项目/WBS/成本/风险  项目 {len(projects)}（含 1 混合父 + 1 敏捷子），"
              f"WBS 叶子 {n_wbs}")

        seed_work_orders(db, parks, buildings, enterprises)
        devices = seed_devices(db, parks, buildings)
        seed_device_inspections(db, devices)
        seed_energy(db, parks, buildings)
        seed_safety(db, parks, buildings, enterprises)
        print(f"[10/12] 物业/设备/能耗/安全  设备 {len(devices)}")

        pols = seed_policies(db, enterprises)
        seed_policy_matches(db, pols, enterprises)
        seed_service_requests(db, enterprises)
        seed_activities_rooms(db, parks, buildings, enterprises)
        seed_parking_vehicles_visitors(db, parks, enterprises)
        print(f"[11/12] 政策/服务/活动/门禁  政策 {len(pols)}")

        seed_ai_data(db, users, parks)
        seed_approvals(db, users, projects, enterprises)
        seed_notifications(db, users)
        seed_audit_logs(db, users)
        seed_reports(db, users, parks, projects)
        print("[12/12] AI/审批/通知/审计/报表  完成")

        seed_payments(db)
        print("        收款流水              完成")

        # 回填项目上的里程碑冗余计数。
        # 这两列（projects.milestone_total / milestone_done）此前从未被写入，
        # 全库恒为 0，曾导致驾驶舱「里程碑达成率」、项目列表「里程碑进度」
        # 与 AI 项目洞察三处都显示 0%（读取方现已改为从 milestones 表聚合，
        # 这里保证列值与源表一致，不再自相矛盾）。
        n_synced = refresh_project_milestone_counters(db)
        print(f"        里程碑计数回填        已同步 {n_synced} 个项目")

        db.commit()

        print("-" * 76)
        print("  数据统计（来自各数据表 COUNT）")
        print("-" * 76)
        total, n_tables = 0, 0
        for table in sorted(Base.metadata.sorted_tables, key=lambda t: t.name):
            try:
                c = db.query(func.count()).select_from(table).scalar() or 0
            except Exception:
                c = -1
            n_tables += 1
            total += max(c, 0)
            print(f"  {table.name:<30} {c:>10,}")
        print("-" * 76)
        print(f"  合计：{n_tables} 张表 / {total:,} 条记录")
        print(f"  耗时：{(dt.datetime.now() - t0).total_seconds():.1f} 秒")
        print("=" * 76)
        print("  ⚠️  以上全部为演示数据（is_demo=True / remark=演示数据），仅用于功能演示。")
        print("=" * 76)
    except Exception as exc:
        db.rollback()
        import traceback
        traceback.print_exc()
        raise SystemExit(f"数据生成失败：{exc}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

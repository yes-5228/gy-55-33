from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.lockers.models import LockerCell
from apps.parcels.models import Parcel
from apps.returns.models import ReturnOrder
from apps.returns.services import create_return_order, complete_return_order


class CreateReturnOrderTests(TestCase):
    def setUp(self):
        self.cell = LockerCell.objects.create(
            code="M001", zone="A区", size=LockerCell.Size.MEDIUM,
            status=LockerCell.Status.OCCUPIED,
        )
        self.parcel = Parcel.objects.create(
            tracking_no="SF1234567890",
            sender_name="张三",
            receiver_name="李四",
            receiver_phone="13800138000",
            carrier="顺丰",
            locker_cell=self.cell,
            pickup_code="654321",
            status=Parcel.Status.STORED,
        )
        self.valid_data = {
            "parcel_id": self.parcel.id,
            "reason": ReturnOrder.Reason.TIMEOUT,
            "operator": "管理员",
            "remark": "超过7天未取",
        }

    def test_create_return_order_success(self):
        order = create_return_order(self.valid_data.copy())
        self.assertEqual(order.parcel_id, self.parcel.id)
        self.assertEqual(order.status, ReturnOrder.Status.PENDING)
        self.assertEqual(order.reason, ReturnOrder.Reason.TIMEOUT)
        self.assertEqual(order.operator, "管理员")
        self.assertEqual(order.remark, "超过7天未取")
        self.assertIsNotNone(order.created_at)

    def test_create_return_order_parcel_becomes_return_pending(self):
        create_return_order(self.valid_data.copy())
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.status, Parcel.Status.RETURN_PENDING)

    def test_create_return_order_cell_remains_occupied(self):
        create_return_order(self.valid_data.copy())
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.OCCUPIED)

    def test_create_return_order_status_linkage(self):
        order = create_return_order(self.valid_data.copy())
        self.parcel.refresh_from_db()
        self.cell.refresh_from_db()
        self.assertEqual(order.status, ReturnOrder.Status.PENDING)
        self.assertEqual(self.parcel.status, Parcel.Status.RETURN_PENDING)
        self.assertEqual(self.cell.status, LockerCell.Status.OCCUPIED)

    def test_create_return_order_parcel_not_found(self):
        data = self.valid_data.copy()
        data["parcel_id"] = 99999
        with self.assertRaises(ValidationError) as ctx:
            create_return_order(data)
        self.assertIn("快件不存在", str(ctx.exception))

    def test_create_return_order_not_stored_parcel(self):
        self.parcel.status = Parcel.Status.PICKED_UP
        self.parcel.save()
        with self.assertRaises(ValidationError) as ctx:
            create_return_order(self.valid_data.copy())
        self.assertIn("只有已入库且未取件的快件可发起退件", str(ctx.exception))

    def test_create_return_order_duplicate_returns_error(self):
        create_return_order(self.valid_data.copy())
        with self.assertRaises(ValidationError) as ctx:
            create_return_order(self.valid_data.copy())
        self.assertIn("只有已入库且未取件的快件可发起退件", str(ctx.exception))

    def test_create_return_order_with_existing_return_order(self):
        ReturnOrder.objects.create(
            parcel=self.parcel,
            reason=ReturnOrder.Reason.TIMEOUT,
            operator="管理员",
        )
        with self.assertRaises(ValidationError) as ctx:
            create_return_order(self.valid_data.copy())
        self.assertIn("该快件已经存在退件单", str(ctx.exception))

    def test_create_return_order_with_return_pending_parcel(self):
        self.parcel.status = Parcel.Status.RETURN_PENDING
        self.parcel.save()
        with self.assertRaises(ValidationError) as ctx:
            create_return_order(self.valid_data.copy())
        self.assertIn("只有已入库且未取件的快件可发起退件", str(ctx.exception))


class CompleteReturnOrderTests(TestCase):
    def setUp(self):
        self.cell = LockerCell.objects.create(
            code="M001", zone="A区", size=LockerCell.Size.MEDIUM,
            status=LockerCell.Status.OCCUPIED,
        )
        self.parcel = Parcel.objects.create(
            tracking_no="SF1234567890",
            sender_name="张三",
            receiver_name="李四",
            receiver_phone="13800138000",
            carrier="顺丰",
            locker_cell=self.cell,
            pickup_code="654321",
            status=Parcel.Status.RETURN_PENDING,
        )
        self.return_order = ReturnOrder.objects.create(
            parcel=self.parcel,
            reason=ReturnOrder.Reason.TIMEOUT,
            operator="管理员",
            status=ReturnOrder.Status.PENDING,
        )

    def test_complete_return_order_success(self):
        order = complete_return_order(self.return_order)
        self.assertEqual(order.status, ReturnOrder.Status.COMPLETED)
        self.assertIsNotNone(order.completed_at)

    def test_complete_return_order_parcel_becomes_returned(self):
        complete_return_order(self.return_order)
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.status, Parcel.Status.RETURNED)
        self.assertIsNotNone(self.parcel.returned_at)

    def test_complete_return_order_cell_becomes_empty(self):
        complete_return_order(self.return_order)
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.EMPTY)
        self.assertIsNotNone(self.cell.last_opened_at)

    def test_complete_return_order_status_linkage(self):
        order = complete_return_order(self.return_order)
        self.parcel.refresh_from_db()
        self.cell.refresh_from_db()
        self.assertEqual(order.status, ReturnOrder.Status.COMPLETED)
        self.assertEqual(self.parcel.status, Parcel.Status.RETURNED)
        self.assertEqual(self.cell.status, LockerCell.Status.EMPTY)

    def test_complete_return_order_not_pending(self):
        self.return_order.status = ReturnOrder.Status.COMPLETED
        self.return_order.save()
        with self.assertRaises(ValidationError) as ctx:
            complete_return_order(self.return_order)
        self.assertIn("只有待处理退件单可完成", str(ctx.exception))

    def test_complete_return_order_cannot_complete_cancelled(self):
        self.return_order.status = ReturnOrder.Status.CANCELLED
        self.return_order.save()
        with self.assertRaises(ValidationError) as ctx:
            complete_return_order(self.return_order)
        self.assertIn("只有待处理退件单可完成", str(ctx.exception))

    def test_complete_return_order_cell_remains_occupied_on_failure(self):
        self.return_order.status = ReturnOrder.Status.COMPLETED
        self.return_order.save()
        try:
            complete_return_order(self.return_order)
        except ValidationError:
            pass
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.OCCUPIED)

    def test_complete_return_order_parcel_remains_pending_on_failure(self):
        self.return_order.status = ReturnOrder.Status.COMPLETED
        self.return_order.save()
        try:
            complete_return_order(self.return_order)
        except ValidationError:
            pass
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.status, Parcel.Status.RETURN_PENDING)


class FullReturnFlowTests(TestCase):
    def setUp(self):
        self.cell = LockerCell.objects.create(
            code="M001", zone="A区", size=LockerCell.Size.MEDIUM,
            status=LockerCell.Status.EMPTY,
        )
        self.parcel_data = {
            "tracking_no": "SF1234567890",
            "sender_name": "张三",
            "receiver_name": "李四",
            "receiver_phone": "13800138000",
            "carrier": "顺丰",
        }

    def test_full_inbound_to_return_flow(self):
        from apps.parcels.services import inbound_parcel

        parcel = inbound_parcel(self.parcel_data.copy())
        self.assertEqual(parcel.status, Parcel.Status.STORED)
        cell = LockerCell.objects.get(id=parcel.locker_cell_id)
        self.assertEqual(cell.status, LockerCell.Status.OCCUPIED)

        order = create_return_order({
            "parcel_id": parcel.id,
            "reason": ReturnOrder.Reason.REJECTED,
            "operator": "操作员小王",
        })
        parcel.refresh_from_db()
        cell.refresh_from_db()
        self.assertEqual(order.status, ReturnOrder.Status.PENDING)
        self.assertEqual(parcel.status, Parcel.Status.RETURN_PENDING)
        self.assertEqual(cell.status, LockerCell.Status.OCCUPIED)

        complete_return_order(order)
        parcel.refresh_from_db()
        cell.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(order.status, ReturnOrder.Status.COMPLETED)
        self.assertEqual(parcel.status, Parcel.Status.RETURNED)
        self.assertEqual(cell.status, LockerCell.Status.EMPTY)

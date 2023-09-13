import pytest

from ib_tools.bracket_legs import FixedStop
from ib_tools.execution_models import (
    AbstractExecModel,
    BaseExecModel,
    EventDrivenExecModel,
    OcaExecModel,
)


def test_AbstraExecModel_is_abstract():
    with pytest.raises(TypeError):
        AbstractExecModel()


def test_BaseExecModel_instantiates():
    bem = BaseExecModel()
    assert isinstance(bem, BaseExecModel)


def test_EventDrivenExecModel_instantiates():
    edem = EventDrivenExecModel()
    assert isinstance(edem, EventDrivenExecModel)


def test_BaseExecModel_order_validator_works_with_correct_keys():
    open_order = {"orderType": "LMT", "lmtPrice": 5}
    bem = BaseExecModel({"open_order": open_order})
    assert bem.open_order == open_order


def test_BaseExecModel_order_validator_raises_with_incorrect_keys():
    open_order = {"orderType": "LMT", "price123": 5}
    with pytest.raises(ValueError) as excinfo:
        BaseExecModel({"open_order": open_order})
    assert "price123" in str(excinfo.value)


def test_position_id():
    em = EventDrivenExecModel(stop=FixedStop(10))
    id1 = em.position_id()
    id2 = em.position_id()
    assert id1 == id2


def test_position_id_reset():
    em = EventDrivenExecModel(stop=FixedStop(10))
    id1 = em.position_id()
    id2 = em.position_id(True)
    assert id1 != id2


def test_oca_group_OcaExecModel():
    e = OcaExecModel(stop=FixedStop(1))
    oca_group = e.oca_group()
    assert isinstance(oca_group, str)
    assert len(oca_group) > 10
    assert oca_group.endswith("00000")


def test_oca_group_is_not_position_id():
    e = OcaExecModel(stop=FixedStop(1))
    oca_group = e.oca_group()
    position_id = e.position_id()
    assert oca_group != position_id

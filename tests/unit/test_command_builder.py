"""Unit tests for CommandBuilder — vendor-specific CLI command generation."""

import pytest
from core.command_builder import CommandBuilder, SUPPORTED_DEVICE_TYPES


@pytest.fixture
def builder():
    return CommandBuilder()


@pytest.fixture
def bgp_config():
    return {
        "local_asn": 65001,
        "router_id": "10.0.0.1",
        "neighbors": [
            {
                "neighbor_ip": "192.168.1.2",
                "remote_asn": 65002,
                "description": "peer-r2",
                "next_hop_self": True,
            },
            {
                "neighbor_ip": "192.168.1.3",
                "remote_asn": 65003,
                "description": "peer-r3",
                "shutdown": True,
            },
        ],
        "networks": ["10.0.0.0/8", "172.16.0.0/12"],
    }


@pytest.fixture
def ospf_config():
    return {
        "process_id": 1,
        "router_id": "10.0.0.1",
        "areas": [
            {
                "area_id": "0",
                "area_type": "normal",
                "networks": ["10.0.0.0/8"],
                "interfaces": [
                    {
                        "name": "GigabitEthernet0/0/0/0",
                        "cost": 10,
                        "hello_interval": 10,
                        "dead_interval": 40,
                        "passive": False,
                    }
                ],
            },
            {
                "area_id": "1",
                "area_type": "stub",
                "networks": ["192.168.1.0/24"],
                "interfaces": [
                    {
                        "name": "GigabitEthernet0/0/0/1",
                        "passive": True,
                    }
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Supported device types
# ---------------------------------------------------------------------------

class TestSupportedDeviceTypes:
    def test_all_expected_types_supported(self, builder):
        assert "cisco_xr" in SUPPORTED_DEVICE_TYPES
        assert "cisco_ios" in SUPPORTED_DEVICE_TYPES
        assert "junos" in SUPPORTED_DEVICE_TYPES
        assert "arista_eos" in SUPPORTED_DEVICE_TYPES
        assert "nokia_sros" in SUPPORTED_DEVICE_TYPES

    def test_unsupported_type_raises(self, builder):
        with pytest.raises(ValueError, match="Unsupported device type"):
            builder.build({"bgp": {}}, "huawei_vrp")

    def test_build_returns_list(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_xr")
        assert isinstance(cmds, list)
        assert len(cmds) > 0

    def test_empty_config_returns_empty_list(self, builder):
        cmds = builder.build({}, "cisco_xr")
        assert cmds == []


# ---------------------------------------------------------------------------
# Cisco XR BGP
# ---------------------------------------------------------------------------

class TestCiscoXRBGP:
    def test_router_bgp_stanza(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_xr")
        assert "router bgp 65001" in cmds

    def test_router_id_present(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_xr")
        assert any("bgp router-id 10.0.0.1" in c for c in cmds)

    def test_neighbor_remote_as(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_xr")
        assert any("neighbor 192.168.1.2" in c for c in cmds)
        assert any("remote-as 65002" in c for c in cmds)

    def test_neighbor_description(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_xr")
        assert any("description peer-r2" in c for c in cmds)

    def test_neighbor_shutdown(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_xr")
        assert any("shutdown" in c for c in cmds)

    def test_next_hop_self(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_xr")
        assert any("next-hop-self" in c for c in cmds)

    def test_address_family_block(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_xr")
        assert any("address-family ipv4 unicast" in c for c in cmds)

    def test_no_router_id_if_missing(self, builder):
        config = {"bgp": {"local_asn": 65001, "neighbors": []}}
        cmds = builder.build(config, "cisco_xr")
        assert not any("router-id" in c for c in cmds)


# ---------------------------------------------------------------------------
# Cisco IOS BGP
# ---------------------------------------------------------------------------

class TestCiscoIOSBGP:
    def test_router_bgp_stanza(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_ios")
        assert "router bgp 65001" in cmds

    def test_router_id_present(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_ios")
        assert any("bgp router-id 10.0.0.1" in c for c in cmds)

    def test_log_neighbor_changes(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_ios")
        assert any("log-neighbor-changes" in c for c in cmds)

    def test_neighbor_remote_as_inline(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_ios")
        assert any("192.168.1.2 remote-as 65002" in c for c in cmds)

    def test_address_family_ipv4(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_ios")
        assert any("address-family ipv4" in c for c in cmds)
        assert any("exit-address-family" in c for c in cmds)

    def test_network_mask_syntax(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_ios")
        # IOS uses: network 10.0.0.0 mask 255.0.0.0
        assert any("network 10.0.0.0 mask 255.0.0.0" in c for c in cmds)

    def test_neighbor_activate_in_afi(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_ios")
        assert any("192.168.1.2 activate" in c for c in cmds)


# ---------------------------------------------------------------------------
# JunOS BGP
# ---------------------------------------------------------------------------

class TestJunosBGP:
    def test_autonomous_system(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "junos")
        assert any("autonomous-system 65001" in c for c in cmds)

    def test_router_id(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "junos")
        assert any("router-id 10.0.0.1" in c for c in cmds)

    def test_ebgp_group(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "junos")
        assert any("group EBGP type external" in c for c in cmds)

    def test_neighbor_peer_as(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "junos")
        assert any("192.168.1.2 peer-as 65002" in c for c in cmds)

    def test_ibgp_group_for_same_asn(self, builder):
        config = {
            "bgp": {
                "local_asn": 65001,
                "neighbors": [
                    {"neighbor_ip": "10.1.1.1", "remote_asn": 65001},
                ],
            }
        }
        cmds = builder.build(config, "junos")
        assert any("group IBGP type internal" in c for c in cmds)

    def test_set_format_commands(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "junos")
        for cmd in cmds:
            assert cmd.startswith("set "), f"JunOS command must start with 'set': {cmd}"


# ---------------------------------------------------------------------------
# Arista EOS BGP
# ---------------------------------------------------------------------------

class TestAristaEOSBGP:
    def test_router_bgp_stanza(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "arista_eos")
        assert "router bgp 65001" in cmds

    def test_router_id(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "arista_eos")
        assert any("router-id 10.0.0.1" in c for c in cmds)

    def test_neighbor_remote_as(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "arista_eos")
        assert any("192.168.1.2 remote-as 65002" in c for c in cmds)

    def test_address_family_ipv4(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "arista_eos")
        assert any("address-family ipv4" in c for c in cmds)

    def test_network_in_afi(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "arista_eos")
        assert any("network 10.0.0.0/8" in c for c in cmds)


# ---------------------------------------------------------------------------
# Cisco XR OSPF
# ---------------------------------------------------------------------------

class TestCiscoXROSPF:
    def test_router_ospf_stanza(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "cisco_xr")
        assert "router ospf 1" in cmds

    def test_router_id(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "cisco_xr")
        assert any("router-id 10.0.0.1" in c for c in cmds)

    def test_area_stanza(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "cisco_xr")
        assert any("area 0" in c for c in cmds)

    def test_interface_with_cost(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "cisco_xr")
        assert any("interface GigabitEthernet0/0/0/0" in c for c in cmds)
        assert any("cost 10" in c for c in cmds)

    def test_hello_dead_interval(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "cisco_xr")
        assert any("hello-interval 10" in c for c in cmds)
        assert any("dead-interval 40" in c for c in cmds)

    def test_passive_interface(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "cisco_xr")
        assert any("passive enable" in c for c in cmds)


# ---------------------------------------------------------------------------
# Cisco IOS OSPF
# ---------------------------------------------------------------------------

class TestCiscoIOSOSPF:
    def test_router_ospf_stanza(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "cisco_ios")
        assert "router ospf 1" in cmds

    def test_log_adjacency_changes(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "cisco_ios")
        assert any("log-adjacency-changes" in c for c in cmds)

    def test_network_wildcard_syntax(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "cisco_ios")
        # IOS uses wildcard: network 10.0.0.0 0.255.255.255 area 0
        assert any("0.255.255.255" in c for c in cmds)

    def test_stub_area(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "cisco_ios")
        assert any("area 1 stub" in c for c in cmds)


# ---------------------------------------------------------------------------
# JunOS OSPF
# ---------------------------------------------------------------------------

class TestJunosOSPF:
    def test_set_format_ospf(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "junos")
        ospf_cmds = [c for c in cmds if "protocols ospf" in c]
        assert len(ospf_cmds) > 0
        for cmd in ospf_cmds:
            assert cmd.startswith("set ")

    def test_area_id_dotted_notation(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "junos")
        assert any("0.0.0.0" in c for c in cmds)

    def test_interface_hello_interval(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "junos")
        assert any("hello-interval 10" in c for c in cmds)


# ---------------------------------------------------------------------------
# Arista EOS OSPF
# ---------------------------------------------------------------------------

class TestAristaEOSOSPF:
    def test_router_ospf_stanza(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "arista_eos")
        assert "router ospf 1" in cmds

    def test_router_id(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "arista_eos")
        assert any("router-id 10.0.0.1" in c for c in cmds)

    def test_log_adjacency_changes(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "arista_eos")
        assert any("log-adjacency-changes" in c for c in cmds)

    def test_network_with_area(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "arista_eos")
        assert any("network 10.0.0.0/8 area 0" in c for c in cmds)


# ---------------------------------------------------------------------------
# Combined BGP + OSPF
# ---------------------------------------------------------------------------

class TestCombinedConfig:
    def test_bgp_and_ospf_combined(self, builder, bgp_config, ospf_config):
        config = {"bgp": bgp_config, "ospf": ospf_config}
        cmds = builder.build(config, "cisco_xr")
        assert any("router bgp" in c for c in cmds)
        assert any("router ospf" in c for c in cmds)

    def test_bgp_only_no_ospf_commands(self, builder, bgp_config):
        cmds = builder.build({"bgp": bgp_config}, "cisco_xr")
        assert not any("router ospf" in c for c in cmds)

    def test_ospf_only_no_bgp_commands(self, builder, ospf_config):
        cmds = builder.build({"ospf": ospf_config}, "cisco_xr")
        assert not any("router bgp" in c for c in cmds)


# ---------------------------------------------------------------------------
# Rollback / negate
# ---------------------------------------------------------------------------

class TestBuildRollback:
    def test_rollback_cisco_xr_negates_bgp(self, builder, bgp_config):
        neg = builder.build_rollback({"bgp": bgp_config}, "cisco_xr")
        assert any("no router bgp" in c for c in neg)

    def test_rollback_cisco_ios_negates_bgp(self, builder, bgp_config):
        neg = builder.build_rollback({"bgp": bgp_config}, "cisco_ios")
        assert any("no router bgp" in c for c in neg)

    def test_rollback_junos_uses_delete(self, builder, bgp_config):
        neg = builder.build_rollback({"bgp": bgp_config}, "junos")
        for cmd in neg:
            assert cmd.startswith("delete "), f"JunOS rollback must use 'delete': {cmd}"

    def test_rollback_arista_eos_negates(self, builder, bgp_config):
        neg = builder.build_rollback({"bgp": bgp_config}, "arista_eos")
        assert any("no router bgp" in c for c in neg)

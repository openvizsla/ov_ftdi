#include "config.h"
#include <epan/packet.h>

static int proto_usbll = -1;
static int hf_usbll_pid = -1;
static int hf_usbll_flags = -1;
static int ett_usbll = -1;

static const value_string pidnames[] = {
    { 0xA5, "SOF" },
    { 0xC3, "DATA0" },
    { 0x4B, "DATA1" },
    { 0x87, "DATA2" },
    { 0x0F, "MDATA" },
    { 0xE1, "OUT" },
    { 0x69, "IN" },
    { 0x2D, "SETUP" },
    { 0xD2, "ACK" },
    { 0x5A, "NAK" },
    { 0x1E, "STALL" },
    { 0x96, "NYET" },
    { 0x3C, "PRE-ERR" },
    { 0x78, "SPLIT" },
    { 0xB4, "PING" },
    { 0, NULL }
};

void
proto_register_usbll(void)
{
    proto_usbll = proto_register_protocol (
        "USB Link Layer",
        "USBLL",
        "usbll"
    );
}

static void
dissect_usbll(tvbuff_t *tvb, packet_info *pinfo, proto_tree *tree)
{
    guint8 packet_type = tvb_get_guint8(tvb, 2);

    col_set_str(pinfo->cinfo, COL_PROTOCOL, "USBLL");
    col_clear(pinfo->cinfo, COL_INFO);
    col_add_fstr(pinfo->cinfo, COL_INFO, "%s",
                 val_to_str(packet_type, pidnames, "Unknown (0x%02x)"));

    if (tree) {
        proto_item *ti = NULL;
        proto_item *usbll_tree = NULL;

        ti = proto_tree_add_item(tree, proto_usbll, tvb, 0, -1, ENC_NA);
        usbll_tree = proto_item_add_subtree(ti, ett_usbll);
        proto_tree_add_item(usbll_tree, hf_usbll_flags, tvb, 0, 2, ENC_LITTLE_ENDIAN);
        proto_tree_add_item(usbll_tree, hf_usbll_pid, tvb, 2, 1, ENC_LITTLE_ENDIAN);
    }
}

void
proto_reg_handoff_usbll(void)
{
    static dissector_handle_t usbll_handle;

    static hf_register_info hf[] = {
        { &hf_usbll_flags,
            { "Flags", "usbll.flags",
            FT_UINT16, BASE_DEC,
            NULL, 0x0,
            NULL, HFILL }
        },
        { &hf_usbll_pid,
            { "Packet Identifier", "usbll.pid",
            FT_UINT8, BASE_DEC,
            VALS(pidnames), 0x0,
            NULL, HFILL }
        }
    };

    static gint *ett[] = {
        &ett_usbll
    };

    proto_register_field_array(proto_usbll, hf, array_length(hf));
    proto_register_subtree_array(ett, array_length(ett));

    usbll_handle = create_dissector_handle(dissect_usbll, proto_usbll);
    dissector_add_uint("wtap_encap", WTAP_ENCAP_USBLL, usbll_handle);
}

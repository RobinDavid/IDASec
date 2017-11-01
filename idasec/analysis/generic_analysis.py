# -*- coding: utf-8 -*-

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QWidget, QMessageBox
from idasec.commands import *
from idasec.analysis.default_analysis import DefaultAnalysis
from idasec.proto.analysis_config_pb2 import generic_analysis, generic_analysis_results, specific_parameters_t
from idasec.proto.common_pb2 import *
from idasec.formula import SMTFormula
import idasec.utils as utils
from idasec.report_generator import *

import subprocess
import cgi

import idc
import idasec.ui.resources_rc

try:
    _fromUtf8 = QtCore.QString.fromUtf8
except AttributeError:
    _fromUtf8 = lambda s: s

#======================== RESULT CLASS (pb dependant) ========================
def smtpb_to_result(val):
    return {SAT:("SAT", GREEN), UNKNOWN:("UNKNOWN", PURPLE), UNSAT:("UNSAT", RED), TIMEOUT:("TIMEOUT", BLUE)}[val]

class GenericResults:
    def __init__(self, params):
        #-- params
        self.query = params.dba
        self.from_addr, self.to_addr = params.from_addr, params.to_addr
        self.get_formula = params.get_formula
        self.target = params.target_addr

        #-- results
        self.values = []
        self.status = None
        self.color = None
        self.formula = '"'

    def parse(self, data):
        res = generic_analysis_results()
        res.ParseFromString(data)
        for v in res.values:
            self.values.append(v)
        self.formula = res.smt_formula
        self.status, self.color = smtpb_to_result(res.result)

    def has_formula(self):
        return self.get_formula and self.formula != ""

    def has_values(self):
        return self.values != []

    def get_status(self):
        return self.status


#================================  CONFIG CLASS =====================================
#====================================================================================
class GenericAnalysisConfigWidget(QWidget):

    def __init__(self):
        super(GenericAnalysisConfigWidget, self).__init__()
        self.conf = generic_analysis()
        self.setupUi(self)
        self.set_visbility_stuff(False)
        self.satisfiability_radiobutton.setChecked(True)     
        self.from_button.clicked.connect(self.from_button_clicked)
        self.to_button.clicked.connect(self.to_button_clicked)
        self.restrict_from_button.clicked.connect(self.restrict_from_button_clicked)
        self.restrict_to_button.clicked.connect(self.restrict_to_button_clicked)
        self.target_addr_button.clicked.connect(self.target_addr_button_clicked)
        self.dba_help_button.clicked.connect(self.dba_help_button_clicked)
        self.values_radiobutton.toggled.connect(self.values_radiobutton_toggled)

    def set_fields(self, json_fields):
        gen = json_fields["generic_params"]
        if gen.has_key("target_addr"):
            self.target_addr_field.setText(hex(gen["target_addr"]))
        if gen.has_key("dba"):
            self.dba_expr_field.setText(gen["dba"])
        if gen.has_key("limit_values"):
            self.values_limit_spinbox.setValue(gen['limit_values'])
        if gen.has_key("get_formula"):
            self.get_formula_checkbox.setChecked(gen["get_formula"])
        if gen.has_key("from_addr"):
            self.from_field.setText(hex(gen["from_addr"]))
        if gen.has_key("to_addr"):
            self.to_field.setText(hex(gen["to_addr"]))
        if gen.has_key("restrict_values_from"):
            self.restrict_from_field.setText(hex(gen["restrict_values_from"]))
        if gen.has_key("restrict_values_to"):
            self.restrict_to_field.setText(hex(gen['restrict_values_to']))
        if gen.has_key("kind"):
            if gen["kind"] == "VALUES":
                self.values_radiobutton.setChecked(True)
            else:
                self.satisfiability_radiobutton.setChecked(True)


    def serialize(self):
        from_field, to_field = self.from_field.text(), self.to_field.text()
        target_addr = self.target_addr_field.text()
        restrict_from, restrict_to = self.restrict_from_field.text(), self.restrict_to_field.text()
        try:
            if from_field != "":
                self.conf.from_addr = utils.to_addr(from_field)
            if to_field != "":
                self.conf.to_addr = utils.to_addr(to_field)
            if target_addr != "":
                self.conf.target_addr = utils.to_addr(target_addr)
            else:
                print "Target address is mandatory for generic analysis"
                return None
            if restrict_from !=  "":
                self.conf.restrict_values_from =  utils.to_addr(restrict_from)
            if restrict_to != "":
                self.conf.restrict_values_to = utils.to_addr(restrict_to)
        except ValueError:
            print "Invalid values for either from/to or target address"

        dba_expr = self.dba_expr_field.text()
        if dba_expr == "":
            print "DBA Expr field must be filled !"
            return None
        else:
            self.conf.dba = dba_expr

        if self.satisfiability_radiobutton.isChecked():
            self.conf.kind = self.conf.SATISFIABILITY

        if self.values_radiobutton.isChecked():
            self.conf.kind = self.conf.VALUES
            self.conf.limit_values = self.values_limit_spinbox.value()

        if self.get_formula_checkbox.isChecked():
            self.conf.get_formula = True

        try:
            params = specific_parameters_t()
            params.typeid = params.GENERIC
            params.generic_params.CopyFrom(self.conf)
            return params
        except:
            print "Analysis specific arguments serialization failed"
            return None


    def from_button_clicked(self):
        self.from_field.setText(hex(idc.here()))

    def to_button_clicked(self):
        self.to_field.setText(hex(idc.here()))

    def restrict_from_button_clicked(self):
        self.restrict_from_field.setText(hex(idc.here()))

    def restrict_to_button_clicked(self):
        self.restrict_to_field.setText(hex(idc.here()))

    def target_addr_button_clicked(self):
        ea = idc.here()
        self.target_addr_field.setText(hex(ea))
        cmt = idc.RptCmt(ea)
        if cmt is not None:
            if cmt.startswith("//@assert:"):
                expr = cmt.split(":")[1].lstrip()
                self.dba_expr_field.setText(expr)

    def dba_help_button_clicked(self):
        s = '''
All the expression usable are:
- cst: val, val<size>, hexa
- var: eax, al ..
- load/store: @[addr], @[addr,size]
- unary: !e, -e
- binary: e1 bop e2
- restrict: {e, low, high}
- ite: if c e1 else e2

With:
- uop: [-, !(not)]
- bop: [+, -, *u, *s, /, /s, modu, mods, or, and, xor, >>(concat), lshift, rshiftu,
rshifts, lrotate, rrotate, =, <>, <=u, <u, >=u, >u, <=s, <s, >=s, >s, extu, exts]
        '''
        QMessageBox.about(self, u"DBA langage help", unicode(s))


    def values_radiobutton_toggled(self, toggled):
        if toggled:
            self.set_visbility_stuff(True)
        else:
            self.set_visbility_stuff(False)

    def set_visbility_stuff(self, value):
        self.values_limit_spinbox.setVisible(value)
        self.restrict_label.setVisible(value)
        self.restrict_from_label.setVisible(value)
        self.restrict_from_field.setVisible(value)
        self.restrict_from_button.setVisible(value)
        self.restrict_to_label.setVisible(value)
        self.restrict_to_field.setVisible(value)
        self.restrict_to_button.setVisible(value)

    def setupUi(self, generic_analysis_widget):
        def _fromUtf8(s):
            return s
        def _translate(x,y,z):
            return y
        generic_analysis_widget.setObjectName(_fromUtf8("generic_analysis_widget"))
        generic_analysis_widget.resize(292, 196)
        self.verticalLayout = QtWidgets.QVBoxLayout(generic_analysis_widget)
        self.verticalLayout.setObjectName(_fromUtf8("verticalLayout"))
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName(_fromUtf8("horizontalLayout"))
        self.from_label = QtWidgets.QLabel(generic_analysis_widget)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.from_label.sizePolicy().hasHeightForWidth())
        self.from_label.setSizePolicy(sizePolicy)
        self.from_label.setObjectName(_fromUtf8("from_label"))
        self.horizontalLayout.addWidget(self.from_label)
        self.from_field = QtWidgets.QLineEdit(generic_analysis_widget)
        self.from_field.setObjectName(_fromUtf8("from_field"))
        self.horizontalLayout.addWidget(self.from_field)
        self.from_button = QtWidgets.QPushButton(generic_analysis_widget)
        self.from_button.setMaximumSize(QtCore.QSize(25, 25))
        self.from_button.setText(_fromUtf8(""))
        icon = QtGui.QIcon()
        icon.addPixmap(QtGui.QPixmap(_fromUtf8(":/icons/icons/open-iconic-master/png/3x/target-3x.png")), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.from_button.setIcon(icon)
        self.from_button.setIconSize(QtCore.QSize(12, 12))
        self.from_button.setObjectName(_fromUtf8("from_button"))
        self.horizontalLayout.addWidget(self.from_button)
        self.label_2 = QtWidgets.QLabel(generic_analysis_widget)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.label_2.sizePolicy().hasHeightForWidth())
        self.label_2.setSizePolicy(sizePolicy)
        self.label_2.setObjectName(_fromUtf8("label_2"))
        self.horizontalLayout.addWidget(self.label_2)
        self.to_field = QtWidgets.QLineEdit(generic_analysis_widget)
        self.to_field.setObjectName(_fromUtf8("to_field"))
        self.horizontalLayout.addWidget(self.to_field)
        self.to_button = QtWidgets.QPushButton(generic_analysis_widget)
        self.to_button.setMinimumSize(QtCore.QSize(25, 25))
        self.to_button.setMaximumSize(QtCore.QSize(25, 25))
        self.to_button.setText(_fromUtf8(""))
        self.to_button.setIcon(icon)
        self.to_button.setIconSize(QtCore.QSize(12, 12))
        self.to_button.setObjectName(_fromUtf8("to_button"))
        self.horizontalLayout.addWidget(self.to_button)
        self.verticalLayout.addLayout(self.horizontalLayout)
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_2.setObjectName(_fromUtf8("horizontalLayout_2"))
        self.label_3 = QtWidgets.QLabel(generic_analysis_widget)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.label_3.sizePolicy().hasHeightForWidth())
        self.label_3.setSizePolicy(sizePolicy)
        self.label_3.setObjectName(_fromUtf8("label_3"))
        self.horizontalLayout_2.addWidget(self.label_3)
        self.target_addr_field = QtWidgets.QLineEdit(generic_analysis_widget)
        self.target_addr_field.setObjectName(_fromUtf8("target_addr_field"))
        self.horizontalLayout_2.addWidget(self.target_addr_field)
        self.target_addr_button = QtWidgets.QPushButton(generic_analysis_widget)
        self.target_addr_button.setMaximumSize(QtCore.QSize(25, 25))
        self.target_addr_button.setText(_fromUtf8(""))
        self.target_addr_button.setIcon(icon)
        self.target_addr_button.setIconSize(QtCore.QSize(12, 12))
        self.target_addr_button.setObjectName(_fromUtf8("target_addr_button"))
        self.horizontalLayout_2.addWidget(self.target_addr_button)
        spacerItem = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout_2.addItem(spacerItem)
        self.verticalLayout.addLayout(self.horizontalLayout_2)
        self.horizontalLayout_4 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_4.setObjectName(_fromUtf8("horizontalLayout_4"))
        self.dba_label = QtWidgets.QLabel(generic_analysis_widget)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.dba_label.sizePolicy().hasHeightForWidth())
        self.dba_label.setSizePolicy(sizePolicy)
        self.dba_label.setObjectName(_fromUtf8("dba_label"))
        self.horizontalLayout_4.addWidget(self.dba_label)
        self.dba_expr_field = QtWidgets.QLineEdit(generic_analysis_widget)
        self.dba_expr_field.setObjectName(_fromUtf8("dba_expr_field"))
        self.horizontalLayout_4.addWidget(self.dba_expr_field)
        self.dba_help_button = QtWidgets.QPushButton(generic_analysis_widget)
        self.dba_help_button.setMaximumSize(QtCore.QSize(25, 25))
        self.dba_help_button.setText(_fromUtf8(""))
        icon1 = QtGui.QIcon()
        icon1.addPixmap(QtGui.QPixmap(_fromUtf8(":/icons/icons/open-iconic-master/png/3x/question-mark-3x.png")), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.dba_help_button.setIcon(icon1)
        self.dba_help_button.setIconSize(QtCore.QSize(12, 12))
        self.dba_help_button.setObjectName(_fromUtf8("dba_help_button"))
        self.horizontalLayout_4.addWidget(self.dba_help_button)
        self.verticalLayout.addLayout(self.horizontalLayout_4)
        self.horizontalLayout_3 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_3.setObjectName(_fromUtf8("horizontalLayout_3"))
        self.query_label = QtWidgets.QLabel(generic_analysis_widget)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.query_label.sizePolicy().hasHeightForWidth())
        self.query_label.setSizePolicy(sizePolicy)
        self.query_label.setObjectName(_fromUtf8("query_label"))
        self.horizontalLayout_3.addWidget(self.query_label)
        self.satisfiability_radiobutton = QtWidgets.QRadioButton(generic_analysis_widget)
        self.satisfiability_radiobutton.setObjectName(_fromUtf8("satisfiability_radiobutton"))
        self.horizontalLayout_3.addWidget(self.satisfiability_radiobutton)
        self.values_radiobutton = QtWidgets.QRadioButton(generic_analysis_widget)
        self.values_radiobutton.setObjectName(_fromUtf8("values_radiobutton"))
        self.horizontalLayout_3.addWidget(self.values_radiobutton)
        self.values_limit_spinbox = QtWidgets.QSpinBox(generic_analysis_widget)
        self.values_limit_spinbox.setMinimum(1)
        self.values_limit_spinbox.setObjectName(_fromUtf8("values_limit_spinbox"))
        self.horizontalLayout_3.addWidget(self.values_limit_spinbox)
        spacerItem1 = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout_3.addItem(spacerItem1)
        self.verticalLayout.addLayout(self.horizontalLayout_3)
        self.restrict_label = QtWidgets.QLabel(generic_analysis_widget)
        self.restrict_label.setObjectName(_fromUtf8("restrict_label"))
        self.verticalLayout.addWidget(self.restrict_label)
        self.restrict_values_layout = QtWidgets.QHBoxLayout()
        self.restrict_values_layout.setObjectName(_fromUtf8("restrict_values_layout"))
        self.restrict_from_label = QtWidgets.QLabel(generic_analysis_widget)
        self.restrict_from_label.setObjectName(_fromUtf8("restrict_from_label"))
        self.restrict_values_layout.addWidget(self.restrict_from_label)
        self.restrict_from_field = QtWidgets.QLineEdit(generic_analysis_widget)
        self.restrict_from_field.setObjectName(_fromUtf8("restrict_from_field"))
        self.restrict_values_layout.addWidget(self.restrict_from_field)
        self.restrict_from_button = QtWidgets.QPushButton(generic_analysis_widget)
        self.restrict_from_button.setMaximumSize(QtCore.QSize(25, 25))
        self.restrict_from_button.setText(_fromUtf8(""))
        self.restrict_from_button.setIcon(icon)
        self.restrict_from_button.setIconSize(QtCore.QSize(12, 12))
        self.restrict_from_button.setObjectName(_fromUtf8("restrict_from_button"))
        self.restrict_values_layout.addWidget(self.restrict_from_button)
        self.restrict_to_label = QtWidgets.QLabel(generic_analysis_widget)
        self.restrict_to_label.setObjectName(_fromUtf8("restrict_to_label"))
        self.restrict_values_layout.addWidget(self.restrict_to_label)
        self.restrict_to_field = QtWidgets.QLineEdit(generic_analysis_widget)
        self.restrict_to_field.setObjectName(_fromUtf8("restrict_to_field"))
        self.restrict_values_layout.addWidget(self.restrict_to_field)
        self.restrict_to_button = QtWidgets.QPushButton(generic_analysis_widget)
        self.restrict_to_button.setMaximumSize(QtCore.QSize(25, 25))
        self.restrict_to_button.setText(_fromUtf8(""))
        self.restrict_to_button.setIcon(icon)
        self.restrict_to_button.setIconSize(QtCore.QSize(12, 12))
        self.restrict_to_button.setObjectName(_fromUtf8("restrict_to_button"))
        self.restrict_values_layout.addWidget(self.restrict_to_button)
        self.verticalLayout.addLayout(self.restrict_values_layout)
        self.get_formula_checkbox = QtWidgets.QCheckBox(generic_analysis_widget)
        self.get_formula_checkbox.setObjectName(_fromUtf8("get_formula_checkbox"))
        self.verticalLayout.addWidget(self.get_formula_checkbox)
        QtCore.QMetaObject.connectSlotsByName(generic_analysis_widget)
        generic_analysis_widget.setWindowTitle(_translate("generic_analysis_widget", "Form", None))
        self.from_label.setText(_translate("generic_analysis_widget", "From:", None))
        self.label_2.setText(_translate("generic_analysis_widget", "To:", None))
        self.label_3.setText(_translate("generic_analysis_widget", "Target addr:", None))
        self.dba_label.setText(_translate("generic_analysis_widget", "DBA Expr:", None))
        self.query_label.setText(_translate("generic_analysis_widget", "Query:", None))
        self.satisfiability_radiobutton.setText(_translate("generic_analysis_widget", "Satisfiability", None))
        self.values_radiobutton.setText(_translate("generic_analysis_widget", "Values", None))
        self.restrict_label.setText(_translate("generic_analysis_widget", "Restrict values space:", None))
        self.restrict_from_label.setText(_translate("generic_analysis_widget", "From:", None))
        self.restrict_to_label.setText(_translate("generic_analysis_widget", "To:", None))
        self.get_formula_checkbox.setText(_translate("generic_analysis_widget", "Retrieve formula from Binsec", None))


#================================= GENERIC ANALYSIS =================================
#====================================================================================

class GenericAnalysis(DefaultAnalysis):

    config_widget = GenericAnalysisConfigWidget()
    name = "Generic"

    ANNOT_CODE = "Annotate code"
    HIGHLIGHT_CODE = "Highlight dependencies"
    GRAPH_DEPENDENCY = "Generate dependency graph"
    DISASS_UNKNOWN_TARGET = "Disassemble unknown targets"

    def __init__(self, parent, config, is_stream=False, trace=None):
        DefaultAnalysis.__init__(self, parent, config, is_stream, trace)
        #self.setupUi(self)
        self.results = GenericResults(config.additional_parameters.generic_params)
        self.result_widget = GenericAnalysisResultWidget(self)
        self.actions = {self.ANNOT_CODE:           (self.annotate_code, False),
                        self.HIGHLIGHT_CODE:       (self.highlight_dependency, False),
                        self.GRAPH_DEPENDENCY:      (self.graph_dependency, False),
                        self.DISASS_UNKNOWN_TARGET:(self.disassemble_new_targets, False)}
        self.addresses_lighted = set()
        self.backup_comment = {}
        self.formula = SMTFormula()

    def binsec_message_received(self, cmd, data):
        if cmd == ANALYSIS_RESULTS:
            print "Analysis results received !"
            self.results.parse(data)
        else:
            self.log(cmd, data, origin="BINSEC")

    def analysis_terminated(self):
        self.result_widget.post_analysis_stuff(self.results)
        if self.results.has_formula():
            self.formula.parse(self.results.formula)

    def annotate_code(self, enabled):
        if not enabled: #Annotate
            s = ":["+self.results.get_status()+"]"
            if self.results.has_values():
                s+= " vals:["+''.join(["%x," % x for x in self.results.values])[:-1] + "]"
            cmt = idc.RptCmt(self.results.target)
            if cmt != "":
                self.backup_comment[self.results.target] = cmt
                if cmt.startswith("//@assert"):
                    s = cmt + s
                else:
                    s = cmt + "\n" + self.results.query + s
            else:
                s = self.results.query + s
                self.backup_comment[self.results.target] = ""
            idc.MakeRptCmt(self.results.target, s.encode("utf-8", "ignore"))
        else:
            for addr, cmt in self.backup_comment.items():
                idc.MakeRptCmt(addr, cmt)
            self.backup_comment.clear()
        self.actions[self.ANNOT_CODE] = (self.annotate_code, not(enabled))
        self.result_widget.action_selector_changed(self.ANNOT_CODE)

    def highlight_dependency(self, enabled):
        if self.results.has_formula():
            color = 0xffffff if enabled else 0x98FF98
            for addr in self.formula.get_addresses():
                idc.SetColor(addr, idc.CIC_ITEM, color)
        else:
            print "woot ?"
        self.actions[self.HIGHLIGHT_CODE] = (self.highlight_dependency, not(enabled))
        self.result_widget.action_selector_changed(self.HIGHLIGHT_CODE)

    def graph_dependency(self, enabled):
#        print "======= Formula 2 ======"
#        for line in self.formula.formula_to_string():
#            print line
#       print "========================"
        output = "/tmp/slice_rendered"
        self.formula.slice(output)
        res = subprocess.call(["dot", "-Tpdf", output, "-o", output+".pdf"])
        if res != 0:
            print "Something went wrong with dot"
        subprocess.Popen(["xdg-open",output+".pdf"])

    def disassemble_new_targets(self, enabled):
        for value in self.results.values:
            flag = idc.GetFlags(value)
            if not idc.isCode(flag) and idc.isUnknown(flag):
                res = idc.MakeCode(value)
                if res == 0:
                    print "Try disassemble at:"+hex(value)+" KO"
                    #TODO: Rollback ?
                else:
                    print "Try disassemble at:"+hex(value)+" Success !"


#============================= RESULT WIDGET ===============================
#===========================================================================
class GenericAnalysisResultWidget(QWidget):
    def __init__(self, parent):
        QWidget.__init__(self)
        self.setupUi(self)
        self.parent = parent
        # self.result_area.setEnabled(False)
        if self.parent.results.get_formula:
            self.formula_label.setVisible(True)
            self.formula_area.setEnabled(True)
        else:
            self.formula_label.setVisible(False)
            self.formula_area.setVisible(False)
        self.action_selector.setEnabled(False)
        self.action_button.setEnabled(False)
        self.action_selector.addItem(self.parent.ANNOT_CODE)
        self.action_button.clicked.connect(self.action_clicked)
        self.action_selector.currentIndexChanged.connect(self.action_selector_changed)

    def action_selector_changed(self, s):
        _, enabled = self.parent.actions[s]
        if enabled:
            self.action_button.setText("Undo !")
        else:
            self.action_button.setText("Do !")

    def action_clicked(self):
        s = self.action_selector.currentText()
        fun, enabled = self.parent.actions[s]
        fun(enabled)

    def post_analysis_stuff(self, results):
        if results.has_formula():
            self.action_selector.addItem(self.parent.HIGHLIGHT_CODE)
            self.action_selector.addItem(self.parent.GRAPH_DEPENDENCY)
            self.formula_area.setText(self.parent.results.formula)
        if results.has_values():
            self.action_selector.addItem(self.parent.DISASS_UNKNOWN_TARGET)
        self.action_selector.setEnabled(True)
        self.action_button.setEnabled(True)

        report = HTMLReport()
        report.add_title("Results",size=3)
        report.add_table_header(["address","assertion", "status","values"])
        addr = make_cell("%x" % results.target)
        status = make_cell(results.get_status(), color=results.color, bold=True)
        vals = ""
        for value in results.values:
            flag = idc.GetFlags(value)
            type = self.type_to_string(flag)
            vals += "%x type:%s seg:%s fun:%s<br/>" % (value, type, idc.SegName(value), idc.GetFunctionName(value))
        report.add_table_line([addr, make_cell(cgi.escape(results.query)), status, make_cell(vals)])
        report.end_table()
        data = report.generate()
        self.result_area.setHtml(data)

    def type_to_string(self, t):
        if idc.isCode(t):
            return "C"
        elif idc.isData(t):
            return "D"
        elif idc.isTail(t):
            return "T"
        elif idc.isUnknown(t):
            return "Ukn"
        else:
            return "Err"


    def setupUi(self, Form):
        def _fromUtf8(s):
            return s
        def _translate(x,y,z):
            return y
        Form.setObjectName(_fromUtf8("Form"))
        Form.resize(758, 527)
        self.verticalLayout_3 = QtWidgets.QVBoxLayout(Form)
        self.verticalLayout_3.setObjectName(_fromUtf8("verticalLayout_3"))
        self.splitter = QtWidgets.QSplitter(Form)
        self.splitter.setOrientation(QtCore.Qt.Vertical)
        self.splitter.setObjectName(_fromUtf8("splitter"))
        self.verticalLayoutWidget = QtWidgets.QWidget(self.splitter)
        self.verticalLayoutWidget.setObjectName(_fromUtf8("verticalLayoutWidget"))
        self.verticalLayout = QtWidgets.QVBoxLayout(self.verticalLayoutWidget)
        self.verticalLayout.setObjectName(_fromUtf8("verticalLayout"))
        self.result_label = QtWidgets.QLabel(self.verticalLayoutWidget)
        font = QtGui.QFont()
        font.setPointSize(10)
        font.setBold(True)
        font.setItalic(False)
        font.setWeight(75)
        self.result_label.setFont(font)
        self.result_label.setAlignment(QtCore.Qt.AlignCenter)
        self.result_label.setObjectName(_fromUtf8("result_label"))
        self.verticalLayout.addWidget(self.result_label)
        self.result_area = QtWidgets.QTextEdit(self.verticalLayoutWidget)
        self.result_area.setObjectName(_fromUtf8("result_area"))
        self.verticalLayout.addWidget(self.result_area)
        self.verticalLayoutWidget_2 = QtWidgets.QWidget(self.splitter)
        self.verticalLayoutWidget_2.setObjectName(_fromUtf8("verticalLayoutWidget_2"))
        self.verticalLayout_2 = QtWidgets.QVBoxLayout(self.verticalLayoutWidget_2)
        self.verticalLayout_2.setObjectName(_fromUtf8("verticalLayout_2"))
        self.formula_label = QtWidgets.QLabel(self.verticalLayoutWidget_2)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.formula_label.setFont(font)
        self.formula_label.setAlignment(QtCore.Qt.AlignCenter)
        self.formula_label.setObjectName(_fromUtf8("formula_label"))
        self.verticalLayout_2.addWidget(self.formula_label)
        self.formula_area = QtWidgets.QTextEdit(self.verticalLayoutWidget_2)
        self.formula_area.setMinimumSize(QtCore.QSize(0, 0))
        self.formula_area.setObjectName(_fromUtf8("formula_area"))
        self.verticalLayout_2.addWidget(self.formula_area)
        self.verticalLayout_3.addWidget(self.splitter)
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_2.setObjectName(_fromUtf8("horizontalLayout_2"))
        self.action_label = QtWidgets.QLabel(Form)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.action_label.sizePolicy().hasHeightForWidth())
        self.action_label.setSizePolicy(sizePolicy)
        self.action_label.setObjectName(_fromUtf8("action_label"))
        self.horizontalLayout_2.addWidget(self.action_label)
        self.action_selector = QtWidgets.QComboBox(Form)
        self.action_selector.setObjectName(_fromUtf8("action_selector"))
        self.horizontalLayout_2.addWidget(self.action_selector)
        self.action_button = QtWidgets.QPushButton(Form)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.action_button.sizePolicy().hasHeightForWidth())
        self.action_button.setSizePolicy(sizePolicy)
        self.action_button.setMinimumSize(QtCore.QSize(70, 0))
        self.action_button.setObjectName(_fromUtf8("action_button"))
        self.horizontalLayout_2.addWidget(self.action_button)
        self.verticalLayout_3.addLayout(self.horizontalLayout_2)
        QtCore.QMetaObject.connectSlotsByName(Form)
        Form.setWindowTitle(_translate("Form", "Form", None))
        self.result_label.setText(_translate("Form", "Result", None))
        self.formula_label.setText(_translate("Form", "SMT Formula", None))
        self.action_label.setText(_translate("Form", "Action:", None))
        self.action_button.setText(_translate("Form", "Do !", None))

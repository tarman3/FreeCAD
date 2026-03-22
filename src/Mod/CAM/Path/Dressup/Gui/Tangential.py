# -*- coding: utf-8 -*-
# ***************************************************************************
# *   Copyright (c) 2024 sliptonic <shopinthewoods@gmail.com>               *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

from PySide.QtCore import QT_TRANSLATE_NOOP
import FreeCAD
import FreeCADGui
import Path
from Path.Dressup import Tangential as PathDressupTangential
from PathScripts import PathUtils
from Path.Dressup import Utils as PathDressup

if True:
    Path.Log.setLevel(Path.Log.Level.DEBUG, Path.Log.thisModule())
    Path.Log.trackModule(Path.Log.thisModule())
else:
    Path.Log.setLevel(Path.Log.Level.INFO, Path.Log.thisModule())


translate = FreeCAD.Qt.translate


class TaskPanel(object):
    def __init__(self, obj, viewProvider):
        self.obj = obj
        self.viewProvider = viewProvider
        self.form = FreeCADGui.PySideUic.loadUi(":/panels/DressupTangential.ui")

        # Connect UI elements to properties
        self.setupUI()
        self.updateUI()

    def setupUI(self):
        """Setup UI connections."""
        # TODO: Connect UI elements to update functions
        pass

    def updateUI(self):
        """Update UI elements from object properties."""
        if hasattr(self.form, "tangentialAngle"):
            self.form.tangentialAngle.setValue(self.obj.TangentialAngle)
        if hasattr(self.form, "oscillationAngle"):
            self.form.oscillationAngle.setValue(self.obj.OscillationAngle)
        if hasattr(self.form, "oscillationFrequency"):
            self.form.oscillationFrequency.setValue(self.obj.OscillationFrequency)
        if hasattr(self.form, "enableOscillation"):
            self.form.enableOscillation.setChecked(self.obj.EnableOscillation)

    def updateFromUI(self):
        """Update object properties from UI elements."""
        if hasattr(self.form, "tangentialAngle"):
            self.obj.TangentialAngle = self.form.tangentialAngle.value()
        if hasattr(self.form, "oscillationAngle"):
            self.obj.OscillationAngle = self.form.oscillationAngle.value()
        if hasattr(self.form, "oscillationFrequency"):
            self.obj.OscillationFrequency = self.form.oscillationFrequency.value()
        if hasattr(self.form, "enableOscillation"):
            self.obj.EnableOscillation = self.form.enableOscillation.isChecked()

    def accept(self):
        self.updateFromUI()
        FreeCADGui.ActiveDocument.resetEdit()
        FreeCADGui.Control.closeDialog()
        FreeCAD.ActiveDocument.recompute()

    def reject(self):
        FreeCADGui.Control.closeDialog()
        FreeCAD.ActiveDocument.recompute()


class ViewProvider(object):
    def __init__(self, vobj):
        self.obj = vobj.Object
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def setEdit(self, vobj, mode=0):
        FreeCADGui.Control.closeDialog()
        panel = TaskPanel(vobj.Object, vobj)
        FreeCADGui.Control.showDialog(panel)
        return True

    def unsetEdit(self, vobj, mode):
        return False

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None

    def claimChildren(self):
        if hasattr(self.obj.Base, "InList"):
            for i in self.obj.Base.InList:
                if hasattr(i, "Group"):
                    group = i.Group
                    for g in group:
                        if g.Name == self.obj.Base.Name:
                            group.remove(g)
                    i.Group = group
        return [self.obj.Base]

    def onDelete(self, arg1=None, arg2=None):
        """this makes sure that the base operation is added back to the project and visible"""
        Path.Log.debug("Deleting Dressup")
        if arg1.Object and arg1.Object.Base:
            FreeCADGui.ActiveDocument.getObject(arg1.Object.Base.Name).Visibility = True
            job = PathUtils.findParentJob(self.obj)
            if job:
                job.Proxy.addOperation(arg1.Object.Base, arg1.Object)
            arg1.Object.Base = None
        return True

    def canDragObjects(self):
        return True

    def canDropObjects(self):
        return True

    def canDragObject(self, dragged_object):
        return True

    def canDropObject(self, incoming_object):
        return hasattr(incoming_object, "Path")

    def dropObject(self, feature, incoming_object):
        feature.Base = incoming_object

    def getIcon(self):
        if getattr(PathDressup.baseOp(self.obj), "Active", True):
            return ":/icons/CAM_Dressup.svg"
        else:
            return ":/icons/CAM_OpActive.svg"


class CommandTangentialDressup:
    def GetResources(self):
        return {
            "Pixmap": "CAM_Dressup",
            "MenuText": QT_TRANSLATE_NOOP("CAM_DressupTangential", "Tangential"),
            "ToolTip": QT_TRANSLATE_NOOP(
                "CAM_DressupTangential", "Create a Tangential Dressup object from a selected path"
            ),
        }

    def IsActive(self):
        if FreeCAD.ActiveDocument is not None:
            for o in FreeCAD.ActiveDocument.Objects:
                if o.Name[:3] == "Job":
                    return True
        return False

    def Activated(self):
        # check that the selection contains exactly what we want
        selection = FreeCADGui.Selection.getSelection()
        if len(selection) != 1:
            Path.Log.error(translate("CAM_DressupTangential", "Select one toolpath object") + "\n")
            return
        baseObject = selection[0]
        if not baseObject.isDerivedFrom("Path::Feature"):
            Path.Log.error(
                translate("CAM_DressupTangential", "The selected object is not a toolpath") + "\n"
            )
            return
        if baseObject.isDerivedFrom("Path::FeatureCompoundPython"):
            Path.Log.error(translate("CAM_DressupTangential", "Select a Profile object"))
            return

        # everything ok!
        FreeCAD.ActiveDocument.openTransaction("Create Tangential Dressup")
        FreeCADGui.addModule("Path.Dressup.Gui.Tangential")
        FreeCADGui.addModule("PathScripts.PathUtils")
        FreeCADGui.doCommand(
            'obj = FreeCAD.ActiveDocument.addObject("Path::FeaturePython", "TangentialDressup")'
        )
        FreeCADGui.doCommand("base = FreeCAD.ActiveDocument." + selection[0].Name)
        FreeCADGui.doCommand("job = PathScripts.PathUtils.findParentJob(base)")
        FreeCADGui.doCommand("dbo = Path.Dressup.Tangential.DressupTangential(obj, base, job)")
        FreeCADGui.doCommand("job.Proxy.addOperation(obj, base)")
        FreeCADGui.doCommand("Path.Dressup.Gui.Tangential.ViewProvider(obj.ViewObject)")
        FreeCAD.ActiveDocument.commitTransaction()
        FreeCAD.ActiveDocument.recompute()


if FreeCAD.GuiUp:
    FreeCADGui.addCommand("CAM_DressupTangential", CommandTangentialDressup())

# -*- coding: utf-8 -*-
# SPDX-License-Identifier: LGPL-2.1-or-later
# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2022 FreeCAD Project Association                        *
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

import FreeCAD
import FreeCADGui
import Path
import PathScripts.PathUtils as PathUtils
from Path.Dressup.Utils import toolController

from PySide.QtCore import QT_TRANSLATE_NOOP

import math
import time

__title__ = "CAM Path Compound with Tool Controller"
__author__ = ""
__url__ = "https://forum.freecad.org/viewtopic.php?t=96765"
__doc__ = ""


if False:
    Path.Log.setLevel(Path.Log.Level.DEBUG, Path.Log.thisModule())
    Path.Log.trackModule(Path.Log.thisModule())
else:
    Path.Log.setLevel(Path.Log.Level.INFO, Path.Log.thisModule())


translate = FreeCAD.Qt.translate


class ObjectCompound:
    def __init__(self, obj):
        self.obj = obj
        obj.addProperty(
            "App::PropertyBool",
            "Active",
            "Path",
            QT_TRANSLATE_NOOP(
                "App::Property", "Make False, to prevent operation from generating code"
            ),
        )
        obj.addProperty(
            "App::PropertyString",
            "Comment",
            "Path",
            QT_TRANSLATE_NOOP("App::Property", "An optional comment for this Operation"),
        )
        obj.addProperty(
            "App::PropertyString",
            "UserLabel",
            "Path",
            QT_TRANSLATE_NOOP("App::Property", "User Assigned Label"),
        )
        obj.addProperty(
            "App::PropertyLink",
            "ToolController",
            "Path",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "The tool controller that will be used to calculate the path",
            ),
        )
        obj.addProperty(
            "App::PropertyString",
            "CycleTime",
            "Path",
            QT_TRANSLATE_NOOP("App::Property", "Operations Cycle Time Estimation"),
        )
        obj.Proxy = self
        obj.Active = True
        obj.setEditorMode("CycleTime", 1)  # read-only
        obj.setEditorMode("ToolController", 3)  # read-only and hidden

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def onDelete(self, obj, args):
        print("onDelete from class ObjectCompound")
        # Does not work. Do not undestand why ...
        # Someone who read this, please explain the reason )))
        # For workaround added onDelete() to class ViewProviderCompound
        return True

    def onChanged(self, obj, prop):
        return None

    def onDocumentRestored(self, obj):
        return None

    def execute(self, obj):
        # Set ToolController if identical for all operations in Group
        obj.ToolController = None
        if isinstance(obj.Group, list) and len(obj.Group) > 0:
            tcs = [op.ToolController for op in obj.Group]
            if len(set(tcs)) == 1 and tcs[0]:
                obj.ToolController = tcs[0]

        # Do not generate Path and clear current Path,
        # if PathCompound not Active or ToolController not set
        if not obj.Active or not obj.ToolController:
            obj.Path = Path.Path()
        else:
            obj.Path = Compound(obj.Group).getPath()
            obj.CycleTime = self.getCycleTimeEstimate(obj)

        if not obj.ToolController:
            Path.Log.error(
                translate("CAM", "Tool Controllers of the combined objects is different or None.")
            )
            return translate("CAM", "Tool Error")

    def getCycleTimeEstimate(self, obj):
        tc = obj.ToolController
        if tc is None or tc.ToolNumber == 0:
            Path.Log.error(translate("CAM", "No Tool Controller selected."))
            return translate("CAM", "Tool Error")

        hFeedrate = tc.HorizFeed.Value
        vFeedrate = tc.VertFeed.Value
        hRapidrate = tc.HorizRapid.Value
        vRapidrate = tc.VertRapid.Value

        if (hFeedrate == 0 or vFeedrate == 0) and not Path.Preferences.suppressAllSpeedsWarning():
            Path.Log.warning(
                translate(
                    "CAM",
                    "Tool Controller feedrates required to calculate the cycle time.",
                )
            )
            return translate("CAM", "Feedrate Error")

        if (
            hRapidrate == 0 or vRapidrate == 0
        ) and not Path.Preferences.suppressRapidSpeedsWarning():
            Path.Log.warning(
                translate(
                    "CAM",
                    "Add Tool Controller Rapid Speeds on the SetupSheet for more accurate cycle times.",
                )
            )

        # Get the cycle time in seconds
        seconds = obj.Path.getCycleTime(hFeedrate, vFeedrate, hRapidrate, vRapidrate)
        if math.isnan(seconds):
            return translate("CAM", "Cycletime Error")

        # Convert the cycle time to a HH:MM:SS format
        cycleTime = time.strftime("%H:%M:%S", time.gmtime(seconds))
        return cycleTime


class Compound:
    def __init__(self, GroupList):
        if GroupList and isinstance(GroupList, list):
            self.GroupList = GroupList
        else:
            self.GroupList = list()

    def preprocessPath(self, pathObj):
        # Here we can change gcode by template
        preprocessPathObj = pathObj
        return preprocessPathObj

    def getPath(self):
        # Call this method on an instance of the class
        # to generate and return Path of the combined operations
        combinedPathObj = Path.Path()
        for operation in self.GroupList:
            combinedPathObj.addCommands(operation.Path.Commands)
        resultPathObj = self.preprocessPath(combinedPathObj)

        # return combined and pre-processed Path object
        return resultPathObj


class ViewProviderCompound:
    def __init__(self, vobj):
        self.attach(vobj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def attach(self, vobj):
        self.vobj = vobj
        self.obj = vobj.Object

    def claimChildren(self):
        if hasattr(self.obj, "Group"):
            return self.obj.Group
        else:
            return []

    def getIcon(self):
        return ":/icons/CAM_CompoundTC.svg"

    def onDelete(self, vobj, args=None):
        jobObj = PathUtils.findParentJob(self.obj)
        for operation in self.obj.Group:
            PathUtils.addToJob(operation, jobObj.Name)
            operation.ViewObject.Visibility = True
        return True


class commandPathCompoundTC:
    def GetResources(self):
        return {
            "Pixmap": "CAM_CompoundTC",
            "MenuText": QT_TRANSLATE_NOOP("CAM_PathCompoundTC", "Path Compound TC"),
            "ToolTip": QT_TRANSLATE_NOOP(
                "CAM_PathCompoundTC", "Creates compound of paths with tool controller"
            ),
        }

    def IsActive(self):
        selections = [
            sel.isDerivedFrom("Path::Feature") for sel in FreeCADGui.Selection.getSelection()
        ]
        return selections and all(selections)

    def Activated(self):
        doc = FreeCAD.ActiveDocument

        groupObjs = []
        selection = FreeCADGui.Selection.getSelection()
        for sel in selection:
            if isinstance(sel.Proxy, Path.Op.Base.ObjectOp):
                sel.ViewObject.Visibility = False
                groupObjs.append(sel)

        jobObj = PathUtils.findParentJob(groupObjs[0])
        compoundObj = doc.addObject("Path::FeatureCompoundPython", "PathCompound")
        compoundObj.ViewObject.Proxy = 0
        compoundObj.ViewObject.Proxy = ViewProviderCompound(compoundObj.ViewObject)
        PathUtils.addToJob(compoundObj, jobObj.Name)
        compoundObj.Proxy = ObjectCompound(compoundObj)
        compoundObj.Group = groupObjs

        # Remove Path objects from 'Operations' group to exclude gcode duplication
        jobObj.Operations.removeObjects(groupObjs)

        doc.recompute()


if FreeCAD.GuiUp:
    # register the FreeCAD command
    FreeCADGui.addCommand("CAM_PathCompoundTC", commandPathCompoundTC())

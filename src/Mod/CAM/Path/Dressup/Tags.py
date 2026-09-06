# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2017 sliptonic <shopinthewoods@gmail.com>
# SPDX-FileNotice: Part of the FreeCAD project.

################################################################################
#                                                                              #
#   FreeCAD is free software: you can redistribute it and/or modify            #
#   it under the terms of the GNU Lesser General Public License as             #
#   published by the Free Software Foundation, either version 2.1              #
#   of the License, or (at your option) any later version.                     #
#                                                                              #
#   FreeCAD is distributed in the hope that it will be useful,                 #
#   but WITHOUT ANY WARRANTY; without even the implied warranty                #
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                    #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with FreeCAD. If not, see https://www.gnu.org/licenses       #
#                                                                              #
################################################################################

from Path.Dressup.Gui.TagPreferences import HoldingTagPreferences
from PathScripts.PathUtils import waiting_effects
from PySide.QtCore import QT_TRANSLATE_NOOP
import FreeCAD
import Path
import Path.Op.Util as PathOpUtil
import Path.Dressup.Utils as PathDressup
from PathScripts import PathUtils
import copy
import math

# lazily loaded modules
from lazy_loader.lazy_loader import LazyLoader

Part = LazyLoader("Part", globals(), "Part")

# Regular tolerance 1e-6 in some case will result short edges 1e-6,
# which is incompatible with Part.sortEdges()
TOL = 1e-5

logger = Path.Log.getModuleLoggerWithLevelOrDebug(Path.Log.Level.INFO, False)

translate = FreeCAD.Qt.translate


class Tag:
    def __init__(self, nr, x, y, width, height, angle, radius, enabled=True):
        self.nr = nr
        self.x = x
        self.y = y
        self.width = math.fabs(width)
        self.height = math.fabs(height)
        self.actualHeight = self.height
        self.angle = math.fabs(angle)
        self.radius = radius
        self.enabled = enabled

        # initialized later
        self.toolRadius = None
        self.solid = None
        self.z = None

    def fullWidth(self):
        return 2 * self.toolRadius + self.width

    def originAt(self, z):
        return FreeCAD.Vector(self.x, self.y, z)

    def bottom(self):
        return self.z

    def top(self):
        return self.z + self.actualHeight

    def createSolidsAt(self, z, R):
        self.z = z
        self.toolRadius = R
        r1 = self.fullWidth() / 2
        height = self.height + 0.1
        radius = 0
        if Path.Geom.isRoughly(90, self.angle) and height > 0:
            # cylinder
            self.solid = Part.makeCylinder(r1, height)
            radius = min(min(self.radius, r1), self.height)
        elif self.angle > 0.0 and height > 0.0:
            # cone
            rad = math.radians(self.angle)
            tangens = math.tan(rad)
            dr = height / tangens
            if dr < r1:
                # with top
                r2 = r1 - dr
                s = height / math.sin(rad)
                radius = min(r2, s) * math.tan((math.pi - rad) / 2) * 0.95
            else:
                # triangular
                r2 = 0
                height = r1 * tangens + 0.1
                self.actualHeight = height
            self.solid = Part.makeCone(r1, r2, height)
        else:
            # degenerated case - no tag
            self.solid = Part.makeSphere(r1 / 10000)
        if not Path.Geom.isRoughly(0, R):  # testing is easier if the solid is not rotated
            angle = -Path.Geom.getAngle(self.originAt(0)) * 180 / math.pi
            self.solid.rotate(FreeCAD.Vector(), FreeCAD.Vector(0, 0, 1), angle)
        orig = self.originAt(z - 0.1)
        self.solid.translate(orig)
        radius = min(self.radius, radius)
        if not Path.Geom.isRoughly(0, radius):
            self.solid = self.solid.makeFillet(radius, [self.solid.Edges[0]])

    def nextIntersectionClosestTo(self, edge, solid, refPt):
        # debugEdge(edge, 'intersects_')

        if not edge.BoundBox.intersect(solid.BoundBox):
            return None
        vertexes = edge.common(solid, 0.01).Vertexes
        if vertexes:
            pt = min(vertexes, key=lambda v: (v.Point - refPt).Length).Point
            return pt
        return None

    def intersects(self, edge, param):
        if self.enabled:
            zFirst = edge.valueAt(edge.FirstParameter).z
            zLast = edge.valueAt(edge.LastParameter).z
            zMax = self.top()
            if any(z < zMax and not Path.Geom.isRoughly(z, zMax, 0.01) for z in (zFirst, zLast)):
                return self.nextIntersectionClosestTo(edge, self.solid, edge.valueAt(param))
        return None


class MapWireToTag:
    def __init__(self, edge, tag, i, hSpeed, vSpeed, tolerance):
        self.tag = tag
        self.hSpeed = hSpeed
        self.vSpeed = vSpeed
        self.tolerance = tolerance
        if Path.Geom.pointsCoincide(edge.valueAt(edge.FirstParameter), i):
            tail = edge
            self.commands = []
        elif Path.Geom.pointsCoincide(edge.valueAt(edge.LastParameter), i):
            self.commands = Path.Geom.cmdsForEdge(
                edge,
                hSpeed=self.hSpeed,
                vSpeed=self.vSpeed,
                tol=tolerance,
            )
            tail = None
        else:
            e, tail = Path.Geom.splitEdgeAt(edge, i)
            self.commands = Path.Geom.cmdsForEdge(
                e,
                hSpeed=self.hSpeed,
                vSpeed=self.vSpeed,
                tol=tolerance,
            )
            self.initialEdge = edge
        self.tail = tail
        self.edges = []
        self.entry = i
        self.complete = False

        # initialized later
        self.edgePoints = None
        self.entryEdges = None
        self.exit = None
        self.exitEdges = None
        self.finalEdge = None
        self.realEntry = None
        self.realExit = None

    def addEdge(self, edge):
        self.edges.append(edge)

    def cleanupEdges(self, edges):
        # want to remove all edges from the wire itself, and all internal struts
        if not edges:
            return edges

        # remove any edge that has a point inside the tag solid
        # and collect all edges that are connected to the entry and/or exit
        self.entryEdges = []
        self.exitEdges = []
        self.edgePoints = []
        # Part.show(self.tag.solid)
        for i, e in enumerate(copy.copy(edges)):
            # Part.show(e)
            p1 = e.valueAt(e.FirstParameter)
            p2 = e.valueAt(e.LastParameter)
            # print(i, p1, p2)
            if self.tag.solid.isInside(e.discretize(3)[1], Path.Geom.Tolerance, False):
                # print("  cleanupEdges", i, "  midpoint inside tag, remove this edge")
                edges.remove(e)
            else:
                self.edgePoints.append(p1)
                self.edgePoints.append(p2)
                if Path.Geom.edgeConnectsTo(e, self.entry, TOL):
                    # print("   ", i, "entry edge")
                    self.entryEdges.append(e)
                elif Path.Geom.edgeConnectsTo(e, self.exit, TOL):
                    # print("   ", i, "exit edge")
                    self.exitEdges.append(e)

        # print("  self.entryEdges", self.entry, len(self.entryEdges))
        # print("  self.exitEdges", self.exit, len(self.exitEdges))
        # if there are no edges connected to entry/exit,
        # we need to add in the missing segment and collect the new entry/exit edges.
        if not self.entryEdges:
            self.realEntry = min(self.edgePoints, key=lambda p: (p - self.entry).Length)
            self.entryEdges = [e for e in edges if Path.Geom.edgeConnectsTo(e, self.realEntry, TOL)]
            edges.append(Part.makeLine(self.entry, self.realEntry))
            # print("    <<< added extra entry line")
        else:
            self.realEntry = None

        if not self.exitEdges:
            self.realExit = min(self.edgePoints, key=lambda p: (p - self.exit).Length)
            self.exitEdges = [e for e in edges if Path.Geom.edgeConnectsTo(e, self.realExit, TOL)]
            edges.append(Part.makeLine(self.realExit, self.exit))
            # print("    >>> added extra exit line")
        else:
            self.realExit = None

        # if there are 2 edges attached to entry/exit, throw away that is lower
        for ee in (self.entryEdges, self.exitEdges):
            if len(ee) > 1:
                # print("  several edges attached to entry/exit !!!")
                bb = sorted(e.BoundBox.ZMax for e in ee)
                for i in range(len(bb) - 1):
                    if ee[i] in edges:
                        edges.remove(ee[i])

        # print("  cleanupEdges", len(edges))
        return edges

    def orderAndFlipEdges(self, edges):
        if not edges:
            return edges
        for e in edges:
            continue
            Part.show(e)
        # wire = Part.Wire(Part.__sortEdges__(edges))
        wire = Part.Wire(Part.sortEdges(edges, TOL)[0])
        # Part.show(wire)
        wire = PathOpUtil.discretizeWire(wire, self.tolerance)
        # Part.show(wire)
        oEdges = PathOpUtil._orientEdges(wire.Edges)
        # Part.show(wire)
        p = oEdges[0].firstVertex().Point
        if Path.Geom.pointsCoincide(p, self.entry, TOL):
            return oEdges
        elif Path.Geom.pointsCoincide(p, self.exit, TOL):
            wire = Part.Wire(oEdges)
            wire = Path.Geom.flipWire(wire)
            return wire.Edges
        else:
            print("ERRROR points no coincide")

    def shell(self):
        if len(self.edges) > 1 and hasattr(self, "initialEdge"):
            wire = Part.Wire(self.initialEdge)
        else:
            edge = self.edges[0]
            if Path.Geom.pointsCoincide(
                edge.valueAt(edge.FirstParameter),
                self.finalEdge.valueAt(self.finalEdge.FirstParameter),
            ):
                wire = Part.Wire(self.finalEdge)
            elif hasattr(self, "initialEdge") and Path.Geom.pointsCoincide(
                edge.valueAt(edge.FirstParameter),
                self.initialEdge.valueAt(self.initialEdge.FirstParameter),
            ):
                wire = Part.Wire(self.initialEdge)
            else:
                wire = Part.Wire(edge)

        for edge in self.edges[1:]:
            if Path.Geom.pointsCoincide(
                edge.valueAt(edge.FirstParameter),
                self.finalEdge.valueAt(self.finalEdge.FirstParameter),
            ):
                wire.add(self.finalEdge)
            else:
                wire.add(edge)

        shell = wire.extrude(FreeCAD.Vector(0, 0, self.tag.height + 1))
        nullFaces = [f for f in shell.Faces if Path.Geom.isRoughly(f.Area, 0)]
        if nullFaces:
            return shell.removeShape(nullFaces)
        return shell

    def commandsForEdges(self):
        commands = []
        if not self.edges:
            return []
        else:
            shape = self.shell().common(self.tag.solid, self.tolerance)
            if not shape.Edges:
                Part.show(self.shell())
                Part.show(self.tag.solid)
            cleanupEdges = self.cleanupEdges(shape.Edges)
            orderAndFlipEdges = self.orderAndFlipEdges(cleanupEdges)
            if orderAndFlipEdges:
                for e in orderAndFlipEdges:
                    commands.extend(
                        Path.Geom.cmdsForEdge(
                            e,
                            hSpeed=self.hSpeed,
                            vSpeed=self.vSpeed,
                            tol=self.tolerance,
                        )
                    )
            if commands:
                return commands

        self.tag.enabled = False
        for e in self.edges:
            commands.extend(
                Path.Geom.cmdsForEdge(
                    e,
                    hSpeed=self.hSpeed,
                    vSpeed=self.vSpeed,
                    tol=self.tolerance,
                )
            )
        return commands

    def add(self, edge):
        self.tail = None
        self.finalEdge = edge
        if self.tag.solid.isInside(edge.valueAt(edge.LastParameter), Path.Geom.Tolerance, True):
            self.addEdge(edge)
        else:
            i = self.tag.intersects(edge, edge.LastParameter)
            if not i:
                i = edge.valueAt(edge.FirstParameter)
            if Path.Geom.pointsCoincide(i, edge.valueAt(edge.LastParameter)):
                self.addEdge(edge)
            else:
                if Path.Geom.pointsCoincide(i, edge.valueAt(edge.FirstParameter)):
                    self.tail = edge
                else:
                    e, tail = Path.Geom.splitEdgeAt(edge, i)
                    self.addEdge(e)
                    self.tail = tail
                self.exit = i
                self.complete = True
                self.commands.extend(self.commandsForEdges())

    def mappingComplete(self):
        return self.complete


class _RapidEdges:
    def __init__(self, rapid):
        self.rapid_coords = set()

        # Calculate precision based on Path.Geom.Tolerance
        # e.g., 0.001 -> 3 decimal places
        try:
            tol = Path.Geom.Tolerance
            self.precision = max(0, math.ceil(-math.log10(tol)))
        except (AttributeError, ValueError, OverflowError):
            self.precision = 6  # Reasonable default

        for edge in rapid:
            self.markRapid(edge)

    def _get_coords_key(self, edge):
        """Generates a hashable tuple of rounded coordinates."""
        try:
            if not isinstance(edge.Curve, (Part.Line, Part.LineSegment)):
                return None

            v0 = edge.Vertexes[0].Point
            v1 = edge.Vertexes[1].Point

            return (
                round(v0.x, self.precision),
                round(v0.y, self.precision),
                round(v0.z, self.precision),
                round(v1.x, self.precision),
                round(v1.y, self.precision),
                round(v1.z, self.precision),
            )
        except (AttributeError, IndexError):
            return None

    def isRapid(self, edge):
        key = self._get_coords_key(edge)
        return key is not None and key in self.rapid_coords

    def markRapid(self, edge):
        key = self._get_coords_key(edge)
        if key is not None:
            self.rapid_coords.add(key)


class PathData:
    def __init__(self, obj):
        self.obj = obj
        path = PathUtils.getPathWithPlacement(obj.Base)
        self.wire, rapid, _ = Path.Geom.wireForPath(path)
        self.rapid = _RapidEdges(rapid)
        if self.wire:
            self.edges = self.wire.Edges
        else:
            self.edges = []
        self.baseWires = self.findBottomWires(self.edges)

    def findBottomWires(self, edges):
        minZ, maxZ = self.findZLimits(edges)
        self.minZ = minZ
        self.maxZ = maxZ
        bottom = [
            e
            for e in edges
            if Path.Geom.isRoughly(e.Vertexes[0].Point.z, minZ)
            and Path.Geom.isRoughly(e.Vertexes[1].Point.z, minZ)
        ]
        self.bottomEdges = Part.sortEdges(bottom)
        return [Part.Wire(se) for se in self.bottomEdges]

    def supportsTagGeneration(self):
        return self.baseWires is not None

    def findZLimits(self, edges):
        # not considering arcs and spheres in Z direction, find the highest and lowest Z values
        minZ = 99999999999
        maxZ = -99999999999
        for e in edges:
            if self.rapid.isRapid(e):
                continue
            for v in e.Vertexes:
                minZ = min(v.Point.z, minZ)
                maxZ = max(v.Point.z, maxZ)
        return minZ, maxZ

    def shortestAndLongestPathEdge(self, wire):
        edges = sorted(wire.Edges, key=lambda e: e.Length)
        return edges[0], edges[-1]

    def generateTags(
        self, obj, minCount=2, maxCount=4, width=None, height=None, angle=None, radius=None
    ):
        print("generateTags", minCount, maxCount)
        tags = []
        maxLength = max(w.Length for w in self.baseWires)
        for wire in self.baseWires:
            optimalCount = Path.Geom.ceil(wire.Length / maxLength * maxCount)
            numberTags = int(max(minCount, optimalCount))

            # copy edge list into python array for (much) faster random access
            Edges = list(wire.Edges)

            tagDistance = wire.Length / numberTags
            print("numberTags", numberTags, "  tagDistance", round(tagDistance, 2))

            W = width if width else self.defaultTagWidth()
            print("W", W)
            H = height if height else self.defaultTagHeight()
            A = angle if angle else self.defaultTagAngle()
            R = radius if radius else self.defaultTagRadius()

            # start assigning tags on the longest segment
            shortestEdge, longestEdge = self.shortestAndLongestPathEdge(wire)
            startIndex = 0
            for i in range(len(Edges)):
                edge = Edges[i]
                if Path.Geom.isRoughly(edge.Length, longestEdge.Length):
                    startIndex = i
                    break
            print("startIndex", startIndex)

            startEdge = Edges[startIndex]
            print("startEdge.Length", round(startEdge.Length, 2))
            startCount = int(startEdge.Length / tagDistance)
            if longestEdge.Length > 2 * shortestEdge.Length:
                startCount += 1

            lastTagLength = (startEdge.Length + (startCount - 1) * tagDistance) / 2
            # lastTagLength = (startCount - 0.5) * startEdge.Length / startCount
            currentLength = startEdge.Length
            print("  currentLength", currentLength, "  lastTagLength", lastTagLength)

            minLength = min(2.0 * W, longestEdge.Length)
            print("minLength", minLength)

            self.useLongEdges = len([e for e in Edges if e.Length >= minLength]) >= numberTags
            print("useLongEdges", self.useLongEdges)

            edgeDict = {}
            if startCount:
                edgeDict = {startIndex: startCount}

            print("indexes", list(range(startIndex + 1, len(Edges))) + list(range(startIndex)))
            for i in list(range(startIndex + 1, len(Edges))) + list(range(startIndex)):
                edge = Edges[i]
                currentLength, lastTagLength = self.processEdge(
                    i, edge, currentLength, lastTagLength, tagDistance, minLength, edgeDict
                )
                print(" ", i, "  currentLength", currentLength, "  lastTagLength", lastTagLength)

            print("edgeDict", edgeDict)
            for i, counter in edgeDict.items():
                edge = Edges[i]
                distance = (edge.LastParameter - edge.FirstParameter) / counter
                for j in range(counter):
                    tag = edge.Curve.value((j + 0.5) * distance)
                    tags.append(Tag(j, tag.x, tag.y, W, H, A, R, True))

        return tags

    def copyTags(self, obj, fromObj, width, height, angle, radius):
        W = width if width else self.defaultTagWidth()
        H = height if height else self.defaultTagHeight()
        A = angle if angle else self.defaultTagAngle()
        R = radius if radius else self.defaultTagRadius()

        tags = []
        j = 0
        for i, pos in enumerate(fromObj.Positions):
            if i in fromObj.Disabled:
                continue
            p = Part.Vertex(FreeCAD.Vector(pos.x, pos.y, self.minZ))
            dists = [w.distToShape(p) for w in self.baseWires]
            dist = min(dists, key=lambda d: d[0])
            at = dist[1][0][0]
            tags.append(Tag(j, at.x, at.y, W, H, A, R, True))
            j += 1

        return tags

    def processEdge(
        self,
        index,
        edge,
        currentLength,
        lastTagLength,
        tagDistance,
        minLength,
        edgeDict,
    ):
        currentLength += edge.Length
        if edge.Length >= minLength or not self.useLongEdges:
            steps = max(0, Path.Geom.ceil((currentLength - lastTagLength) / tagDistance) - 1)
            lastTagLength += steps * tagDistance
            if steps:
                edgeDict[index] = steps

        return currentLength, lastTagLength

    def defaultTagHeight(self):
        op = PathDressup.baseOp(self.obj.Base)
        if hasattr(op, "StartDepth") and hasattr(op, "FinalDepth"):
            pathHeight = (op.StartDepth - op.FinalDepth).Value
        else:
            pathHeight = self.maxZ - self.minZ
        height = HoldingTagPreferences.defaultHeight(pathHeight / 2)
        if height > pathHeight:
            return pathHeight
        return height

    def defaultTagWidth(self):
        maxWidth = 0
        for wire in self.baseWires:
            width = self.shortestAndLongestPathEdge(wire)[1].Length / 10
            maxWidth = max(width, maxWidth)
        return HoldingTagPreferences.defaultWidth(maxWidth)

    def defaultTagAngle(self):
        return HoldingTagPreferences.defaultAngle()

    def defaultTagRadius(self):
        return HoldingTagPreferences.defaultRadius()

    def checkTag(self, tag):
        # Returns True if tag on the base wires
        v = Part.Vertex(tag.originAt(self.minZ))
        if any(v.distToShape(w)[0] < 1 for w in self.baseWires):
            return True
        else:
            logger.info(
                f"Tag #{tag.nr} ({tag.x:.2f}, {tag.y:.2f}, {self.minZ:.2f}) not on base wire - disabling"
            )
            return False

    def pointIsOnPath(self, p):
        v = Part.Vertex(self.pointAtBottom(p))
        logger.debug(f"pt = ({v.X}, {v.Y}, {v.Z})")
        for sortedEdges in self.bottomEdges:
            for e in sortedEdges:
                if Path.Geom.isRoughly(0.0, v.distToShape(e)[0], 0.1):
                    return True
        return False

    def pointAtBottom(self, p):
        return FreeCAD.Vector(p.x, p.y, self.minZ)


class ObjectTagDressup:
    def __init__(self, obj, base):

        obj.addProperty(
            "App::PropertyLink",
            "Base",
            "Base",
            QT_TRANSLATE_NOOP("App::Property", "The base path to modify"),
        )
        obj.addProperty(
            "App::PropertyLength",
            "Width",
            "Tag",
            QT_TRANSLATE_NOOP("App::Property", "Width of tags."),
        )
        obj.addProperty(
            "App::PropertyLength",
            "Height",
            "Tag",
            QT_TRANSLATE_NOOP("App::Property", "Height of tags."),
        )
        obj.addProperty(
            "App::PropertyAngle",
            "Angle",
            "Tag",
            QT_TRANSLATE_NOOP("App::Property", "Angle of tag plunge and ascent."),
        )
        obj.addProperty(
            "App::PropertyLength",
            "Radius",
            "Tag",
            QT_TRANSLATE_NOOP("App::Property", "Radius of the fillet for the tag."),
        )
        obj.addProperty(
            "App::PropertyVectorList",
            "Positions",
            "Tag",
            QT_TRANSLATE_NOOP("App::Property", "Locations of inserted holding tags"),
        )
        obj.addProperty(
            "App::PropertyIntegerList",
            "Disabled",
            "Tag",
            QT_TRANSLATE_NOOP("App::Property", "IDs of disabled holding tags"),
        )
        obj.addProperty(
            "App::PropertyBool",
            "Approximation",
            "Path",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Split B-Spline by arcs and ignore not vertical arcs axis (experimental).",
            ),
        )
        obj.addProperty(
            "App::PropertyBool",
            "AutomaticallyGenerate",
            "Tag",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Generate new tags while recompute",
            ),
        )
        obj.setEditorMode("Approximation", 2)  # hide

        self.obj = obj
        self.solids = []
        self.tags = []
        self.pathData = None
        self.toolRadius = None
        self.mappers = []
        self.minCount = 2
        self.maxCount = 4

        obj.Proxy = self
        obj.Base = base

    def dumps(self):
        state = {}
        state["minCount"] = self.minCount
        state["maxCount"] = self.maxCount
        return state

    def loads(self, state):
        if isinstance(state, dict):
            self.minCount = state.get("minCount", 2)
            self.maxCount = state.get("maxCount", 4)
        else:
            self.minCount = 2
            self.maxCount = 4
        self.solids = []
        self.tags = []
        self.pathData = None
        self.toolRadius = None
        self.mappers = []

    def onChanged(self, obj, prop):
        if prop == "Path" and obj.ViewObject:
            obj.ViewObject.signalChangeIcon()

    def onDocumentRestored(self, obj):
        self.obj = obj
        if not hasattr(obj, "Approximation"):
            obj.addProperty(
                "App::PropertyBool",
                "Approximation",
                "Path",
                QT_TRANSLATE_NOOP(
                    "App::Property",
                    "Split B-Spline by arcs and ignore not vertical arcs axis (experimental).",
                ),
            )
            obj.setEditorMode("Approximation", 2)  # hide

        if not hasattr(obj, "AutomaticallyGenerate"):
            obj.addProperty(
                "App::PropertyBool",
                "AutomaticallyGenerate",
                "Tag",
                QT_TRANSLATE_NOOP(
                    "App::Property",
                    "Generate new tags while recompute",
                ),
            )

    def supportsTagGeneration(self, obj):
        if not self.pathData:
            self.setup(obj)
        return self.pathData.supportsTagGeneration()

    def generateTags(self, obj):
        if self.supportsTagGeneration(obj):
            if self.pathData:
                self.tags = self.pathData.generateTags(
                    obj,
                    self.minCount,
                    self.maxCount,
                    obj.Width.Value,
                    obj.Height.Value,
                    obj.Angle,
                    obj.Radius.Value,
                )
                obj.Positions = [tag.originAt(self.pathData.minZ) for tag in self.tags]
                obj.Disabled = []
                return False
            else:
                self.setup(obj)
                self.execute(obj)
                return True
        else:
            self.tags = []
            obj.Positions = []
            obj.Disabled = []
            return False

    def copyTags(self, obj, fromObj):
        obj.Width = fromObj.Width
        obj.Height = fromObj.Height
        obj.Angle = fromObj.Angle
        obj.Radius = fromObj.Radius

        self.tags = self.pathData.copyTags(
            obj, fromObj, obj.Width.Value, obj.Height.Value, obj.Angle, obj.Radius.Value
        )
        obj.Positions = [tag.originAt(self.pathData.minZ) for tag in self.tags]
        obj.Disabled = []
        return False

    def isValidTagStartIntersection(self, edge, i):
        if Path.Geom.pointsCoincide(i, edge.valueAt(edge.LastParameter)):
            return False
        p1 = edge.valueAt(edge.FirstParameter)
        p2 = edge.valueAt(edge.LastParameter)
        # if this vertical goes up, it can't be the start of a tag intersection
        return not (Path.Geom.pointsCoincide(Path.Geom.xy(p1), Path.Geom.xy(p2)) and p1.z < p2.z)

    def createPath(self, obj, pathData, tags):
        commands = []
        lastEdge = 0
        t = 0
        edge = None

        self.mappers = []
        mapper = None

        job = PathUtils.findParentJob(obj)
        tol = job.GeometryTolerance.Value or 0.01
        tc = PathDressup.toolController(obj.Base)
        horizFeed = (
            obj.Base.HorizFeed.Value
            if hasattr(obj.Base, "HorizFeed") and obj.Base.HorizFeed.Value
            else tc.HorizFeed.Value
        )
        vertFeed = (
            obj.Base.VertFeed.Value
            if hasattr(obj.Base, "VertFeed") and obj.Base.VertFeed.Value
            else tc.VertFeed.Value
        )
        horizRapid = tc.HorizRapid.Value
        vertRapid = tc.VertRapid.Value

        while edge or lastEdge < len(pathData.edges):
            if not edge:
                edge = pathData.edges[lastEdge]
                tagsSorted = sorted(
                    tags, key=lambda t: (t.originAt(t.z) - edge.valueAt(edge.FirstParameter)).Length
                )
                lastEdge += 1

            if mapper:
                mapper.add(edge)
                if mapper.mappingComplete():
                    commands.extend(mapper.commands)
                    edge = mapper.tail
                    mapper = None
                else:
                    edge = None

            if edge:
                tIndex = t % len(tags)
                t += 1
                i = tagsSorted[tIndex].intersects(edge, edge.FirstParameter)
                if i and self.isValidTagStartIntersection(edge, i):
                    # print("    isValidTagStartIntersection")
                    mapper = MapWireToTag(
                        edge,
                        tagsSorted[tIndex],
                        i,
                        hSpeed=horizFeed,
                        vSpeed=vertFeed,
                        tolerance=tol,
                    )
                    self.mappers.append(mapper)
                    edge = mapper.tail

            if not mapper and t >= len(tags):
                # gone through all sorted tags, consume edge and move on
                if edge:
                    if pathData.rapid.isRapid(edge):
                        v = edge.Vertexes[1]
                        if (
                            not commands
                            and Path.Geom.isRoughly(0, v.X)
                            and Path.Geom.isRoughly(0, v.Y)
                            and not Path.Geom.isRoughly(0, v.Z)
                        ):
                            # The very first move is just to move to ClearanceHeight
                            commands.append(Path.Command("G0", {"Z": v.Z, "F": horizRapid}))
                        else:
                            commands.append(
                                Path.Command("G0", {"X": v.X, "Y": v.Y, "Z": v.Z, "F": vertRapid})
                            )
                    else:
                        commands.extend(
                            Path.Geom.cmdsForEdge(
                                edge,
                                approximation=obj.Approximation,
                                hSpeed=horizFeed,
                                vSpeed=vertFeed,
                                tol=tol,
                            )
                        )
                edge = None
                t = 0

        return Path.Path(commands)

    def createTagsPositionDisabled(self, obj, positionsIn, disabledIn):
        rawTags = []
        for i, pos in enumerate(positionsIn):
            tag = Tag(
                i,
                pos.x,
                pos.y,
                obj.Width.Value,
                obj.Height.Value,
                obj.Angle,
                obj.Radius.Value,
                i not in disabledIn,
            )
            tag.enabled = self.pathData.checkTag(tag)
            tag.createSolidsAt(self.pathData.minZ, self.toolRadius)
            rawTags.append(tag)
        # disable all tags that intersect with their previous tag
        prev = None
        tags = []
        positions = []
        disabled = []
        for i, tag in enumerate(rawTags):
            if tag.enabled:
                if prev:
                    if (
                        prev.solid.BoundBox.intersect(tag.solid.BoundBox)
                        and prev.solid.common(tag.solid, 0.01).Faces
                    ):
                        logger.info(f"Tag #{i} intersects with previous tag - disabling\n")
                        logger.debug(f"this tag = {i} [{tag.solid.BoundBox}]")
                        tag.enabled = False
                elif self.pathData.edges:
                    e = self.pathData.edges[0]
                    p0 = e.valueAt(e.FirstParameter)
                    p1 = e.valueAt(e.LastParameter)
                    if tag.solid.isInside(p0, Path.Geom.Tolerance, True) or tag.solid.isInside(
                        p1, Path.Geom.Tolerance, True
                    ):
                        logger.info(f"Tag #{i} intersects with starting point - disabling\n")
                        tag.enabled = False

            if tag.enabled:
                prev = tag
                logger.debug(f"previousTag = {i} [{prev}]")
            else:
                disabled.append(i)
            tag.nr = i  # assign final nr
            tags.append(tag)
            positions.append(tag.originAt(self.pathData.minZ))
        return tags, positions, disabled

    def execute(self, obj):
        self.doExecute(obj)

    def doExecute(self, obj, regen=True):
        if not obj.Base:
            return
        if not obj.Base.isDerivedFrom("Path::Feature"):
            return
        if not obj.Base.Path:
            return
        if not obj.Base.Path.Commands:
            return

        pathData = self.setup(obj)
        if not pathData:
            return

        if obj.AutomaticallyGenerate and regen:
            print("  before generate", obj.Positions, obj.Disabled)
            self.generateTags(obj)
            print("  after generate", obj.Positions, obj.Disabled)

        self.tags = []
        if hasattr(obj, "Positions"):
            self.tags, positions, disabled = self.createTagsPositionDisabled(
                obj, obj.Positions, obj.Disabled
            )
            if obj.Disabled != disabled:
                obj.Positions = positions
                obj.Disabled = disabled

        if not self.tags:
            obj.Path = PathUtils.getPathWithPlacement(obj.Base)
            return

        self.processTags(obj)

        # update disabled in case there are some additional ones
        disabled = copy.copy(self.obj.Disabled)
        solids = []
        for tag in self.tags:
            solids.append(tag.solid)
            if not tag.enabled and tag.nr not in disabled:
                disabled.append(tag.nr)
        self.solids = solids
        if obj.Disabled != disabled:
            obj.Disabled = disabled

    @waiting_effects
    def processTags(self, obj):
        obj.Path = self.createPath(obj, self.pathData, self.tags)

    def setup(self, obj, generate=False):
        self.obj = obj
        pathData = PathData(obj)
        self.toolRadius = float(PathDressup.toolController(obj.Base).Tool.Diameter) / 2
        self.pathData = pathData
        if generate:
            obj.Height = self.pathData.defaultTagHeight()
            obj.Width = self.pathData.defaultTagWidth()
            obj.Angle = self.pathData.defaultTagAngle()
            obj.Radius = self.pathData.defaultTagRadius()
            self.minCount = self.maxCount = HoldingTagPreferences.defaultCount()
            self.generateTags(obj)
        return self.pathData

    def pointIsOnPath(self, obj, point):
        if not self.pathData:
            self.setup(obj)
        return self.pathData.pointIsOnPath(point)

    def pointAtBottom(self, obj, point):
        if not self.pathData:
            self.setup(obj)
        return self.pathData.pointAtBottom(point)


def Create(baseObject, name="DressupTag"):
    """
    Create(basePath, name='DressupTag') … create tag dressup object for the given base path.
    """
    if not baseObject.isDerivedFrom("Path::Feature"):
        logger.error(translate("CAM_DressupTag", "The selected object is not a path") + "\n")
        return None

    if baseObject.isDerivedFrom("Path::FeatureCompoundPython"):
        logger.error(translate("CAM_DressupTag", "Select a profile object"))
        return None

    obj = FreeCAD.ActiveDocument.addObject("Path::FeaturePython", name)
    dbo = ObjectTagDressup(obj, baseObject)
    job = PathUtils.findParentJob(baseObject)
    job.Proxy.addOperation(obj, baseObject)
    dbo.setup(obj, True)
    return obj


logger.notice("Loading CAM_DressupTag… done\n")

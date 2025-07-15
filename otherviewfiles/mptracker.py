#! /usr/bin/env python
# Mouse pupil tracker, these are the functions that do the weight-lifting.

import numpy as np
import cv2
from application.image_processing import Stage
from application.view.widget_utils import AutoFieldWidget
mptracker_ellipse_tickness = 1


def adjust_gamma(image, gamma=1.0):
	# build a lookup table mapping the pixel values [0, 255] to
	# their adjusted gamma values
	invGamma = 1.0 / gamma
	table = np.array([((i / 255.0) ** invGamma) * 255
		for i in np.arange(0, 256)]).astype("uint8")

	return cv2.LUT(image, table)


def getEllipseMask(shape,ePos,eAxes,eAngles,dtype='uint8'):
    tmp = np.zeros(shape = shape,dtype=dtype)
    return cv2.ellipse(tmp,(int(ePos[0]),int(ePos[1])),(int(eAxes[0]),int(eAxes[1])),
                       eAngles[0],0,360,
                       255,-1)


def sobel3x3(img,ksize = 5):
    gradx = cv2.Sobel(img,cv2.CV_32F,1,0,ksize=ksize)
    grady = cv2.Sobel(img,cv2.CV_32F,0,1,ksize=ksize)
    mag = np.sqrt(np.power(gradx,2) + np.power(grady,2)) + 1e-16
    return mag,gradx,grady


def ellipseToContour(pupil_pos,a,b,phi,R=np.linspace(0,2.1*np.pi, 20)):
    xx = pupil_pos[1] + a*np.cos(R)*np.cos(phi) - b*np.sin(R)*np.sin(phi)
    yy = pupil_pos[0] + a*np.cos(R)*np.sin(phi) + b*np.sin(R)*np.cos(phi)
    shape1 = np.zeros((len(xx),1,2),dtype='int32')
    shape1[:,0,0] = xx.astype('int32')
    shape1[:,0,1] = yy.astype('int32')
    return shape1


def getCenterOfMass(contour):
    # center of mass
    M = cv2.moments(contour)
    return (int(M["m10"] / M["m00"]),int(M["m01"] / M["m00"]))


def cropImageWithCoords(npts,img):
    if len(npts):
        pts = np.array(npts).reshape((-1,1,2))
        rect = cv2.boundingRect(pts)
        (x1, y1, w, h) = rect
    else:
        x1,y1 = [0,0]
        w,h = img.shape[:2]
    x2 = x1 + w
    y2 = y1 + h
    return img[y1:y2,x1:x2],(x1,y1,w,h)


# because find contours changed between python versions
(cv2major, _, _) = cv2.__version__.split(".")
if int(cv2major)>3:
    def findContours(im,*args):
        return cv2.findContours(im,*args)[0]        
else:
    def findContours(im,*args):
        return cv2.findContours(im,*args)[1]        


def extractPupilShapeAnalysis(img,params,
                              ROIpoints = [],
                              expectedDiam = None,
                              expectedPosition = None,
                              clahe = None,
                              drawProcessedFrame = False,
                              concatenateBinaryImage = False):
    # Contrast and filtering
    x1,y1 = (0,0)
    if len(img.shape) == 3:
        if img.shape[2] > 1:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        img = np.reshape(img, (img.shape[0], img.shape[1]))
    h, w = img.shape
    roiArea = w*h
    if len(ROIpoints) >= 4:
        img,(x1, y1, w, h) = cropImageWithCoords(ROIpoints,img)
        roiArea = w*h   
        if params['crApprox'] is None:
            try:
                mag,imgx,imgy = sobel3x3(cv2.GaussianBlur(img,(21,21),100))
                minV,maxV,minL,maxL = cv2.minMaxLoc(cv2.GaussianBlur(mag,(21,21),100))
                params['crApprox'] = [maxL[0]+x1,maxL[1]+y1]
            except Exception as e:
                 print(e)
    if not params['crApprox'] is None:
        crA,crB =[int(w*params['crFrac']),int(h*params['crFrac'])]
        crtmp = img[
            params['crApprox'][1] - y1 - crB:params['crApprox'][1] - y1 + crB,
            params['crApprox'][0] - x1 - crA:params['crApprox'][0]  - x1 + crA].copy()
        crtmp = cv2.GaussianBlur(crtmp, (21, 21), 2)
        minV,maxV,minL,maxL = cv2.minMaxLoc(crtmp)
        # Testing the averaging
        maxL = (maxL[0] + params['crApprox'][0] - x1 - crA,
                maxL[1] + params['crApprox'][1] - y1 - crB)
    else:
        maxL = (0,0)
    params['imagecropidx'] = (x1, y1, w, h)
    outimg = img.copy()
    outimg = cv2.cvtColor(outimg,cv2.COLOR_GRAY2RGB)
    img = adjust_gamma(img,params['gamma'])
    # Blurring
    imfilter = params['filterType']
    if imfilter == 'gaussian':
        img = cv2.GaussianBlur(img,
                               (params['filterSize'],
                                params['filterSize']),0)
    elif imfilter == 'median':
        img = cv2.medianBlur(img,
                             params['filterSize'])
    # Contrast equalization        
    img = clahe.apply(img)
    # Morphological operations (Open)
    if params['open_kernelSize'] > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                           (params['open_kernelSize'],
                                            params['open_kernelSize']))
        img = cv2.morphologyEx(img, cv2.MORPH_OPEN, kernel)
    # Morphological operations (Close)
    if params['close_kernelSize'] > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                           (params['close_kernelSize'],
                                            params['close_kernelSize']))
        img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, kernel)
    # Threshold image
    if params['invertThreshold']:
        if not params['crApprox'] is None:
            tmp = img[params['crApprox'][1] - y1 - crB:params['crApprox'][1] - y1 + crB,
                      params['crApprox'][0] - x1 - crA:params['crApprox'][0]  - x1 + crA]
            img[params['crApprox'][1] - y1 - crB:params['crApprox'][1] - y1 + crB,
                params['crApprox'][0] - x1 - crA:params['crApprox'][0]  - x1 + crA] = (tmp.astype(
                    np.float32) * (1. - crtmp/float(maxV))).astype(img.dtype)
        ret,thresh = cv2.threshold(img,params['threshold'],255,0)
        thresh = cv2.bitwise_not(thresh)
    else:
        ret,thresh = cv2.threshold(img,params['threshold'],255,0)
    # Find the contours
    contours = findContours(thresh.copy(),cv2.RETR_LIST,
                       cv2.CHAIN_APPROX_SIMPLE)
    #img = cv2.drawContours(img,
    #                       contours, -1, (20, 0, 250),1)
    # For displaying the corneal reflection
    if drawProcessedFrame:
        outimg = cv2.cvtColor(img,cv2.COLOR_GRAY2RGB)
    if not params['crApprox'] is None:
        outimg = cv2.circle(outimg, maxL, 2, (0,0,255), 1)
    # Shape analysis (get the area of each contour)

    area = np.array([cv2.contourArea(c.astype(np.float32)) for c in contours],
                    dtype = np.float32)
    # Discard very large and very small areas.
    minArea = params['minPupilArea']*roiArea
    maxArea = roiArea*params['maxPupilArea']
    circleIdx = np.where((area > minArea) & (area < maxArea))[0]
    
    font = cv2.FONT_HERSHEY_SIMPLEX
    #for i,c in enumerate(contours):
    #    try:
    #        cX,cY = self.getCenterOfMass(c)
    #        
    #        img = cv2.putText(img,'{0}'.format(round(area[i])),
    #                          (cX,cY), font, 0.5,(0,0,255),2,cv2.LINE_AA)
    #    except:
    #        print(c)
    score = np.ones_like(circleIdx,dtype=np.float64)
    dist = np.ones_like(circleIdx,dtype=np.float64)
    # Try to fit the contours
    mask = np.zeros(thresh.shape,np.uint8)
    tmpe = np.zeros_like(outimg[:,:,0])
    d1,d2 = img.shape
    if not 'pupilApprox' in params.keys() or params['pupilApprox'] is None:
        params['pupilApprox'] = (d2/2+x1,d1/2 + y1)
    
    for e,i in enumerate(circleIdx):
        cX,cY = getCenterOfMass(contours[i])
        #outimg = cv2.putText(outimg,'{0},{1}'.format(params['pupilApprox'][0] - x1,params['pupilApprox'][1] - y1),
        #                     (int(params['pupilApprox'][0])- x1,int(params['pupilApprox'][1])-y1), font, 0.5,(0,255,255),1,cv2.LINE_AA)
        dist[e] = np.sqrt((cX - (params['pupilApprox'][0] - x1))**2 + (cY - (params['pupilApprox'][1] - y1))**2)
        pts = contours[i][:,0,:]
        #distM = np.sqrt((pts[:,0] - cX)**2 + (pts[:,1] - cY)**2)
        #mm,ss = (np.median(distM),np.std(distM))
        #ptsIdx = (distM<mm+ss*1.3) & (distM>mm-ss*1.3)
        #pts = pts[ptsIdx,:]
        if len(pts) > 6: 
            ellipse = cv2.fitEllipse(pts) 
            tmpe[:] = 0
            cv2.ellipse(tmpe,ellipse,255,-1)
            econt = findContours(tmpe,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
            # Remove candidates that are close to the corneal reflection center
            #if np.sqrt((maxL[0] - cX)**2 + (maxL[1] - cY)**2) < h*0.03:
            #    dist = 1000
            # Choose only dark contours?
            # mean_val = cv2.mean(thresh,mask = mask)[0]
            # if mean_val < 128:
            #     dist[e] = 5000            

            # Make it easier to be the pupil if close to the expected location
            # This was buggy and was removed
            if drawProcessedFrame:
                outimg = cv2.drawContours(outimg,
                                          [contours[i]], -1, (70, 0, 150),1)

        else:
            econt = []
        if len(econt):
            # score is the sum of these three factors
            score[e] = cv2.matchShapes(contours[i],econt[0],2,0.0)
            score[e] += (dist[e]**2)
            score[e] += (ellipse[1][1]/ellipse[1][0]) * 100
            #print(e,score[e],dist[e],ellipse[1][1]/ellipse[1][0])
            #print('\n')
            #outimg = cv2.putText(outimg,'{0:4.1f}'.format(score[e]),
            #                     (cX,cY), font, 0.5,(0,50,200),1,cv2.LINE_AA)
        else:
            score[e] = 1000**2
            dist[e] = 1000
        # Text?
    # Get the actual estimate for the contour with best score
    pupil_pos = [np.nan,np.nan]
    (long_axis,short_axis) = [np.nan,np.nan]
    (b,a,phi) = (np.nan,np.nan,np.nan)
    thresh = cv2.cvtColor(thresh,cv2.COLOR_GRAY2RGB)
    score = np.array(score)
    if params['sequentialPupilMode']:
        idx = dist<w*0.1
        score = score[idx]
    # Select the shape with the best score
    if len(score):
        idx = circleIdx[np.argmin(score)]
        # discard outliers (points that are far from the median)
        cX,cY = getCenterOfMass(contours[idx])
        pts = contours[idx][:,0,:]
        dist = np.sqrt((pts[:,0] - cX)**2 + (pts[:,1] - cY)**2)
        mm,ss = (np.median(dist),np.std(dist))
        ptsIdx = (dist<mm+ss*1.) & (dist>mm-ss*1.)
        pts = pts[ptsIdx,:]
        # Estimate pupil diam and position
        if len(pts) > 6:
            ellipse = cv2.fitEllipse(pts)
        else:
            print('Too few points to fit ellipse after removing outliers.')
            ellipse = [[0,0],[0,0]]
        # is it a circle-ish thing?
        if not ellipse[1][0] == 0 and (ellipse[1][1]/ellipse[1][0]) < params['roundIndex']:
            outimg = cv2.drawContours(outimg,
                                        [contours[idx]], -1, (100, 225, 100),1)
            cv2.ellipse(outimg,ellipse,(50,150,250),
                        mptracker_ellipse_tickness,cv2.LINE_AA)
            # Absolute positions
            pupil_pos = np.array([ellipse[0][0],ellipse[0][1]])
            short_axis = ellipse[1][0]
            long_axis = ellipse[1][1]
            phi = ellipse[2]
            pupil_pos[0] += x1
            pupil_pos[1] += y1
            
    if concatenateBinaryImage and drawProcessedFrame:
        outimg = np.concatenate((outimg,thresh),axis=0)
    return (outimg,(maxL[0] + x1,
                    maxL[1] + y1),pupil_pos,
            (short_axis/2.,long_axis/2.),
            (short_axis,long_axis,phi))

class MPTracker(Stage):
    defaults = {
        'contrast_clipLimit':10,
        'contrast_gridSize':5,
        'contrast_roi': True,
        'filterType':'median',
        'filterSize':3,
        'open_kernelSize':0,
        'close_kernelSize':2,
        'threshold':40,
        'minPupilArea': 0.005,
        'maxPupilArea': 0.7,
        'gamma': 1.0,
        'roundIndex': 1.5,
        'crApprox':None,
        'crFrac':0.1,
        'sequentialCrMode':False,
        'sequentialPupilMode':False,
        'points':[],
        'invertThreshold':False,
        'eye_radius_mm':1.8, #this was set to 3*0.8 in the matlab version
        'number_frames':0,
    }
    def __init__(self,parameters = None, drawProcessedFrame=False):
        super().__init__()
        if parameters is None:
            self.parameters = self.defaults.copy()
        else:
            self.parameters = parameters
        for k in self.defaults.keys():
            if not k in self.parameters.keys():
                self.parameters[k] = self.defaults[k]
        #print(self.parameters)
        self.drawProcessedFrame = drawProcessedFrame
        self.set_clhe()
        self.ROIpoints = []
        if 'points' in self.parameters.keys():
            self.setROI(self.parameters['points'])
        self.concatenateBinaryImage=False
    def setROI(self, points):
        self.ROIpoints = points
    def set_clhe(self):
        if (self.parameters['contrast_gridSize']>1):
            self.clahe = cv2.createCLAHE(
                clipLimit=self.parameters['contrast_clipLimit'],
                tileGridSize=(self.parameters['contrast_gridSize'],
                              self.parameters['contrast_gridSize']))
        else:
            class equalizeHist(object):
                def __init__(self,par):
                    self.parameters = par
                    self.gamma = self.parameters['contrast_clipLimit']
                def apply(self,img):
                    if self.gamma>1:
                        return cv2.equalizeHist(img)
                    else:
                        return img
            self.clahe = equalizeHist(self.parameters)

    def _apply(self, img, return_data = False):
        res = extractPupilShapeAnalysis(img,
                                        ROIpoints = self.ROIpoints,
                                        params = self.parameters,
                                        clahe = self.clahe,
                                        concatenateBinaryImage = self.concatenateBinaryImage,
                                        drawProcessedFrame=self.drawProcessedFrame)
        if self.parameters['sequentialCrMode']:
            self.parameters['crApprox'] = res[1]
        if self.parameters['sequentialPupilMode']:
            if not np.isnan(res[2][0]):
                self.parameters['pupilApprox'] = res[2]
        img = res[0]
        data = res[1:]
        if return_data:
            return img, data
        return img

    def getAugmented(self,img,equalize = False):
        (_,pos,M,angles) = self.apply(img)
        
        # Draw the pupil on the image.
        pupil_img = (getEllipseMask(img.shape,pos,M,angles) * 0.5).astype(np.uint8)
        tt = (img*0.5).astype(np.uint8)
        tdat = np.stack([tt,tt+pupil_img,tt]).transpose(1,2,0)
        if equalize:
            clahe = cv2.createCLAHE(clipLimit=20.0, tileGridSize=(11,11))
            for i in range(3):
                tdat[:,:,i] = cv2.equalizeHist(tdat[:,:,i])
        return tdat


class MPTrackerWidget(AutoFieldWidget):
    """Mouse Pupil Tracker Widget
    Uses an adapted implementation from Joao Couto
    Original: https://bitbucket.org/jpcouto/mptracker"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('MPTracker parameters')
        self.mp_tracker = MPTracker(drawProcessedFrame=True)
        self.settings = {'contrast_roi': True,
                        'filterType':'median',
                        'filterSize':3,
                        'open_kernelSize':0,
                        'close_kernelSize':2,
                        'threshold':40,
                        'minPupilArea': 0.005,
                        'maxPupilArea': 0.7,
                        'gamma': 1.0,
                        'roundIndex': 1.5,
                        # 'crApprox':None,
                        'crFrac':0.1,
                        'sequentialCrMode':False,
                        'sequentialPupilMode':False,
                        # 'points':[],
                        'invertThreshold':False,
                        'eye_radius_mm':1.8, #this was set to 3*0.8 in the matlab version
                        'number_frames':0
                         }
        self.init_widgets()

    def apply(self, image):
        return self.mp_tracker.apply(image)
    
    def _apply_parameters(self):
        super()._apply_parameters()
        for setting in self.settings:
            self.mp_tracker.parameters[setting] = self.settings[setting]

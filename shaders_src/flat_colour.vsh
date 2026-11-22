//
//  flat_colour.vsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.
//

//%feature TIRE_INNER_RADIUS_SCALE
//%feature GHOST_ALPHA_MODULATE
//%precompile [TIRE_INNER_RADIUS_SCALE]
//%include utility.xsh
const lowp float c_one = 1.0;

// ======================================================================
// Inputs
// ======================================================================

// Attributes
// ----------------------------------------------------------------------

attribute highp vec3 a_Position;	//%attributeID MT_POS

// Uniforms
// ----------------------------------------------------------------------
#if defined(TIRE_INNER_RADIUS_SCALE) 
	uniform highp vec4 u_TyreGeometry;
	uniform highp vec4 u_TyreRatio;
#endif

// Transformation Matrices
uniform highp mat4 u_ModelToProj;

void main()
{
	// Position
    highp vec4 vertexPosition;

#if defined (TIRE_INNER_RADIUS_SCALE)
    highp float fTyreVertexRadiusBlend = 0.0;
    vertexPosition = tyreInnerRadiusScale(u_ModelToProj, a_Position, u_TyreGeometry, u_TyreRatio, fTyreVertexRadiusBlend);
#else
    vertexPosition = u_ModelToProj * vec4( a_Position, c_one ); 
#endif
    
	gl_Position = vertexPosition;
}


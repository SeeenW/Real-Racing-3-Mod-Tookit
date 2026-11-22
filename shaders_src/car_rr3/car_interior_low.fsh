//
//  car_interior_low.fsh
//
//  Created by bend on 10/07/12.
//  Copyright Electronic Arts 2012. All rights reserved.


//%include utility.xsh

//No dash-specific shader; no cubemap on dash

precision mediump float;

const lowp float c_zero = 0.0;
const lowp float c_one = 1.0;

// Texture samplers
uniform lowp sampler2D s_Texture0;			// Base texture

uniform lowp float u_LightDiffuseScaleFactor;
uniform mediump vec3 u_LightDiffuseColourTimesScaleFactor;
uniform lowp vec3 u_LightAmbientColour;

varying mediump vec2 v_TexCoord0;
//varying highp vec2 v_NdotH;
varying lowp vec3 v_DiffuseColour;

varying highp vec3 v_VertexNormalModelSpace;
varying highp vec3 v_HalfVectorModelSpace;

void main()
{
	lowp vec4 diffuseTexture = texture2DWithBias( s_Texture0, v_TexCoord0 );

	// Per vertex spec read from texture
	//lowp float specTerm = texture2D( s_Texture3, v_NdotH ).a;
	//lowp vec3 specular = v_SpecularColour_Base * specTerm;

	// Diffuse colour
	lowp vec3 diffuse = v_DiffuseColour + (u_LightAmbientColour);

	// Base Texture
	lowp vec4 fragColour = diffuseTexture;

	// Diffuse light
	fragColour.rgb *= diffuse;

#ifdef DIFFUSE_LIGHTING
	gl_FragColor = vec4(diffuse, 1.0);
#else
	gl_FragColor = fragColour;
#endif

	//gl_FragColor.rgb = vec3( v_NdotH.x );
	//gl_FragColor.rgb = vec3( specTerm );
	//gl_FragColor.rgb = v_DiffuseColour;
}


